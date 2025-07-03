from flask import Flask, request, render_template, redirect, url_for, jsonify  
import psycopg2  
import os
import requests
import json
from typing import Dict
from azure.search.documents.models import VectorFilterMode  
from azure.search.documents import SearchClient  
from azure.identity import DefaultAzureCredential  
from azure.core.credentials import AzureKeyCredential  
from azure.search.documents.models import VectorizableTextQuery  
from azure.search.documents.models import QueryType 
from openai import AzureOpenAI  
import time  
import logging
import urllib.parse
import re
  
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)  
  
search_endpoint = os.environ.get('search_endpoint') 
search_key = os.environ.get('search_key')  
search_index = os.environ.get('search_index')
search_api_version = "2025-03-01-preview"
  
# Initialize SearchClient  
search_client = SearchClient(  
    endpoint=search_endpoint,  
    index_name=search_index,  
    credential=AzureKeyCredential(search_key)  
)
  
def rewrite_search_query(search_query):  
    client = AzureOpenAI(  
        azure_deployment=os.environ.get('azure_openai_deployment'),  
        api_version=os.environ.get('azure_openai_api_version'),  
        azure_endpoint=os.environ.get('azure_openai_endpoint'),  
        api_key=os.environ.get('azure_openai_key'),  
    )  
    prompt = '''
Rewrite the following Turkish customer query into a minimal product search query for our ecommerce shop.
Rules:
1. Extract and output only the essential keywords (attributes) with no verbs or full sentences.
2. Retain the original Turkish language except for brand names.
3. Maintain the following attribute order when present:
   a. Color (e.g., "kırmızı")
   b. Main product category or type (e.g., "kışlık üst giyim")
   c. Patterns or key features (e.g., "hayvan resimli")
4. Eliminate unnecessary words such as request verbs (e.g., "istiyorum").
5. Correct possible spelling / typo errors in in query. (pumma > puma, addidas > adidas, aykkabı> ayakkabı)
Query:

''' + search_query
    response = client.chat.completions.create(  
        messages=[{"role": "user", "content": prompt}],  
        model=os.environ.get('azure_openai_model'),  
        max_tokens=50,  
        temperature=0.5,  
    )  
    rewritten_query = response.choices[0].message.content.strip()  
    return rewritten_query 

numeric_fields = ["rating", "price"]  # Numeric fields
collection_fields = ["categories", "tags"]  # Collection fields

def build_filter_query(filter_query):
    if filter_query:
        filters = []
        for filter_item in filter_query.split(','):
            category, values = filter_item.split(':')
            values = values.replace('%20', ' ').split('|')

            if category in collection_fields:
                collection_filter = " or ".join([f"s eq '{value}'" for value in values])
                filters.append(f"{category}/any(s: {collection_filter})")
            elif category in numeric_fields:
                numeric_filter = " or ".join([f"{category} eq {value}" for value in values])
                filters.append(f"({numeric_filter})")
            else:
                string_filter = " or ".join([f"{category} eq '{value}'" for value in values])
                filters.append(f"({string_filter})")

        return ' and '.join(filters)
    else:
        return None

global_filter = ["brandName","genderName","colorName","mainCategoryName","rating"]
global_select = ["productId", "name","brandName", "description", "imageUrl","rating","bestPrice","bestDiscountRate","totalReviewCount","totalOrderCount","categories","favoriCount","filterAttributes","attributes"]
global_search_fields = ["name","brandName","colorName","genderName","mainCategoryName"]
global_embedding_fields = "nameEmbedding, descriptionEmbedding"

debug_search_args = {}

def rest_search_client(**bodyjson) -> Dict:
    url = f"{search_endpoint}/indexes/{search_index}/docs/search?api-version={search_api_version}"
    headers = {
        "Content-Type": "application/json",
        "api-key": search_key
    }

    try:
        response = requests.post(url, headers=headers, json=bodyjson)
        response.raise_for_status()  # Raise exception for bad status codes
        return response.json()
    except requests.exceptions.RequestException as e:
        # Handle request exceptions
        detail = e.response.json().get("error", {}).get("message", str(e))
        raise Exception(f"Search request failed: {str(e)+ ' ' + detail}") from e
    
@app.route('/', methods=['GET', 'POST'])  
def index():  
    starttime = time.time()  
    if request.method == 'POST':  
        search_query = request.form.get('search_query')  
        profile = request.args.get('p', '')
        searchtype = request.args.get('t', 'auto')
        items = int(request.args.get('i', 20))
        sortby = request.args.get('s', '')
        filter_query = request.args.get('f', None)
        force = request.form.get('force', None)

        return redirect(url_for('index', q=search_query, p=profile, t=searchtype, i=items, s=sortby))  
    
    else:   
        search_query = request.args.get('q', '*')
        profile = request.args.get('p', '')
        searchtype = request.args.get('t', 'auto')
        items = int(request.args.get('i', 20))
        sortby = request.args.get('s', '')
        filter_query = request.args.get('f', None)
        force = request.form.get('force', None)
  
    rewritten_query = ''
    debug_notes = ''
    filter_query = request.args.get('f', None)
    filter_query = build_filter_query(filter_query)
    sb_0 = {
        "top": items,
        "count": True,
        "select": ", ".join(global_select),
        "searchFields": ", ".join(global_search_fields),
        "facets": global_filter,
        "scoringProfile": profile,
        "skip": 0
    }

    if filter_query:
        sb_0["filter"] = filter_query

    # if the query length is greater than 5 words, rewrite query
    if len(search_query.split()) >= 5 in search_query:
        search_query = rewrite_search_query(search_query)
    
    # prepare query for fuzzy search
    fuzzy_query = ' '.join(word + '~1' for word in re.findall(r'\b\w+\b', search_query))

    # replace anlynumbers with their original form remowing ~
    fuzzy_query = re.sub(r'(\d+)\s*~\d*', r'\1', fuzzy_query)   

    # if the query is shorter than 3 words, use keyword search
    if len(search_query.split()) < 3 or force != None:
        sb = sb_0.copy()
        sb["queryType"] = "full"
        sb["searchMode"] = "all"
        sb["search"] = search_query
        sb["orderby"] = f"{sortby}"
        result = rest_search_client(**sb)
        # if results are less than 20, use fuzzy search
        if len(result.get("value", [])) < 10:
            sb = sb_0.copy()
            sb["queryType"] = "full"
            sb["searchMode"] = "all"
            sb["search"] = fuzzy_query
            sb["orderby"] = f"{sortby}"
            result = rest_search_client(**sb)

    # if no enough result from above step or original query is 3-4 words fall back to vector search
    if len(search_query.split()) >= 3 or len(result.get("value", [])) < 10:
        sb = sb_0.copy()
        # sb["queryType"] = ""
        sb["searchMode"] = "any" #all
        sb["search"] = search_query
        sb["queryLanguage"] = "tr-TR"
        # sb["captions"] = "extractive"
        # sb["answers"] = "extractive"     
        # sb["semanticConfiguration"] = "semantic-config"
        sb["vectorQueries"] = [
            {
                "kind": "text",
                "text": search_query,
                "k": 50,
                "weight": 0.5,
                "fields": "nameEmbedding"
            },
            {
                "kind": "text",
                "text": search_query,
                "k": 50,
                "weight": 0.2,
                "fields": "descriptionEmbedding"
            },
            # {
            #     "kind": "text",
            #     "text": search_query,
            #     "k": 50,
            #     "weight": 2.0,
            #     "fields": "tagEmbedding",
            # }
            ]
        sb["vectorFilterMode"] = "postFilter"
        sb["top"] = 1000
        result = rest_search_client(**sb)

    # else: # if word is less than 3, use keyword fuzzy search
    #     # if sort by is given, use keyword search        
    #     if True or (sortby != '' and sortby != None):
    #         sb = sb_0.copy()
    #         sb["queryType"] = "full"
    #         sb["searchMode"] = "all"
    #         sb["search"] = fuzzy_query
    #         sb["orderby"] = f"{sortby}"
    #         result = rest_search_client(**sb)
    #         # if no enough result fall back to vector search
    #         if len(result.get("value", [])) < 20:
    #             debug_notes += "Rewritten query: " + sb["search"] + ". "
    #             result = rest_search_client(**sb)
    #     # else sort by best match - semantic ranker
    #     else: 
    #         sb["queryType"] = "semantic"
    #         sb["search"] = fuzzy_query
    #         sb["queryLanguage"] = "tr-TR"
    #         sb["queryRewrites"] = "generative|count-3"
    #         sb["debug"] = "queryRewrites"
    #         sb["semanticConfiguration"] = "semantic-config"
    #         sb["top"] = 100
    #         result = rest_search_client(**sb)
    
    
    products = [x for x in result["value"]]
    if sb.get("orderby",None) == None:
        if sortby != '' and sortby != None:
            products = sorted(products, key=lambda x: x[sortby.split()[0]], reverse= "desc" in sortby)
        products = products[:items] 
    facets = result.get("@search.facets",[])
    debug_search_args = sb
    result_debug = result.get("@search.debug",{"debug_notes":debug_notes})
    total_count = result.get("@odata.count",len(products))

    timeelapsed = time.time() - starttime

    return render_template('index.html', products=products, q=search_query, q2=rewritten_query, p=profile, t=searchtype, i=items, s=sortby, timeelapsed=timeelapsed, facets=facets,debug_info=debug_search_args,total_count=total_count, debug_search_args=debug_search_args, result_debug=result_debug)
    
@app.route('/suggestions')
def get_suggestions():
    query = request.args.get('q', '')
    if len(query) < 2:
        return jsonify([])
    
    fuzzy_query = ' '.join(word + '~2' for word in re.findall(r'\b\w+\b', query))

    # Create search parameters for suggestions
    suggest_params = {
        "search": fuzzy_query,
        "top": 100,
        "select": "brandName",
        "searchFields": "brandName",
        "queryType": "full",
        "searchMode": "all"
    }

    suggest_params2 = {
        "search": fuzzy_query,
        "top": 100,
        "select": "mainCategoryName",
        "searchFields": "mainCategoryName",
        "queryType": "full",
        "searchMode": "all"
    }

    suggestions = []

    try:
        results = rest_search_client(**suggest_params)
        for item in results.get('value', []):
            if 'brandName' in item:
                if item['brandName'] not in suggestions:
                    suggestions.append(item['brandName'])
        
        results2 = rest_search_client(**suggest_params2)
        for item in results2.get('value', []):
            if 'mainCategoryName' in item:
                if item['mainCategoryName'] not in suggestions:
                    suggestions.append(item['mainCategoryName'])
            # elif 'name' in item:
            #     if item['name'] not in suggestions:
            #         suggestions.append(item['name'])
            
        return jsonify(suggestions)
    except Exception as e:
        logging.error(f"Error getting suggestions: {str(e)}")
        return jsonify([])
    
if __name__ == '__main__':  
    app.run(debug=True)