from flask import Flask, request, render_template, redirect, url_for  
import psycopg2  
import os  
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
  
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)  
  
search_endpoint = os.environ.get('search_endpoint')  
search_key = os.environ.get('search_key')  
search_index = os.environ.get('search_index')  
  
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
2. Retain the original Turkish language, including any local slang or informal expressions.
3. Identify and position specific holiday references if mentioned. Examples:
   - Turkish holidays (e.g., "Ramazan", "Kurban Bayramı", "Cumhuriyet Bayramı") 
   - Global holidays (e.g., "Noel", "Yılbaşı")
   If a holiday is mentioned, include it as a separate token and give it appropriate emphasis.
4. Maintain the following attribute order when present:
   a. Color (e.g., "kırmızı")
   b. Main product category or type (e.g., "kışlık üst giyim")
   c. Patterns or key features (e.g., "hayvan resimli")
   d. Holiday/special occasion (if applicable; e.g., "Noel", "Ramazan")
   e. Qualifiers regarding target audience (e.g., convert "kızım için" to "kız" or "oğlum için" to "oğlan", using context to decide if it is a children's product or adult category).
5. Do not replace or remove critical terms; instead, only re-order and tokenize them.
6. Eliminate unnecessary words such as request verbs (e.g., "istiyorum").


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
global_select = ["productId", "name", "description", "imageUrl","rating","bestPrice","bestDiscountRate","totalReviewCount","totalOrderCount","categories","favoriCount","filterAttributes","attributes"]
global_enbedding_fields = "descriptionEmbedding,nameEmbedding,tagEmbedding"

debug_search_args = {}

def vector_search_client_call(search_query, vector_query, items, filter_query, profile, facets=None, sortby=None):
    global debug_search_args
    search_args = {
        "search_text": search_query,
        "vector_queries": [vector_query],
        "include_total_count": True,
        "top": items,
        "vector_filter_mode": VectorFilterMode.POST_FILTER,
        "select": global_select,
        "filter": filter_query,
        "facets": facets or [],
        "scoring_profile": profile
    }
    
    if sortby != '' and sortby != None:
        search_args["query_type"] = QueryType.SIMPLE
        search_args["order_by"] = f"{sortby}"
    else:
        search_args["query_type"] = QueryType.SEMANTIC
        search_args["semantic_configuration_name"] = "semantic-config"

    
    debug_search_args = search_args

    # remove the vector query from the search args to avoid sending it to the search client
    debug_search_args.pop("vector_queries", None)


    results = search_client.search(**search_args)
    logging.debug(f"Vector Search results: {results}")
    if results is None:  # Handle None case
        return []
    return results

def keyword_search_client_call(search_query, items, filter_query, profile, facets=None, sortby=None, ):
    global debug_search_args
    search_args = {
        "search_text": search_query,
        "include_total_count": True,
        "top": items,
        "select": global_select,
        "filter": filter_query,
        "facets": facets or [],
        "scoring_profile": profile
    }
    
    if sortby != '' and sortby != None:
        search_args["query_type"] = QueryType.SIMPLE
        search_args["order_by"] = f"{sortby}"
    else:
        search_args["query_type"] = QueryType.SEMANTIC
        search_args["semantic_configuration_name"] = "semantic-config"


    debug_search_args = search_args

    results = search_client.search(**search_args)
    logging.debug(f"Key Search results: {results}")
    if results is None:  # Handle None case
        return []
    return results
    
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

        return redirect(url_for('index', q=search_query, p=profile, t=searchtype, i=items, s=sortby))  
    
    else:   
        search_query = request.args.get('q', '*')
        profile = request.args.get('p', '')
        searchtype = request.args.get('t', 'auto')
        items = int(request.args.get('i', 20))
        sortby = request.args.get('s', '')
        filter_query = request.args.get('f', None)
  
    results = []  
    rewritten_query = ''  

    filter_query = request.args.get('f', None)

    filter_query = build_filter_query(filter_query)

    # if the query length is greater than 5 words, use rewrite and vector search with filter
    if len(search_query.split()) >= 5:
        rewritten_query = rewrite_search_query(search_query)
        vector_query = VectorizableTextQuery(  
            text=rewritten_query,  
            k_nearest_neighbors=50,  
            fields=global_enbedding_fields 
        )

        #if sortby not null or empty:
        if sortby != '' and sortby != None:
            results = vector_search_client_call(search_query, vector_query, items, filter_query, profile, global_filter, sortby)
        else:
            results = vector_search_client_call(rewritten_query, vector_query, items, filter_query, profile, global_filter, sortby)
    # if the query length is between 3 and 5 words, use vector search with filter
    elif len(search_query.split()) < 5 and len(search_query.split()) > 3:
        if search_query != '':
                vector_query = VectorizableTextQuery(  
                    text=search_query,  
                    k_nearest_neighbors=50,  
                    fields=global_enbedding_fields  
                )  
                results = vector_search_client_call(search_query, vector_query, items, filter_query, profile, global_filter, sortby)
        elif search_query == '':
                # if the search query is empty, perform a keyword search instead as you cannot perform a vector search without a query
                results = keyword_search_client_call(search_query, items, filter_query, profile, global_filter, sortby)
    # if word is less than 3, use keyword search
    else:
        results = keyword_search_client_call(search_query, items, filter_query, profile,  global_filter ,sortby)            
        
    products = [result for result in results]  

    # check if products is empty and if so, dont show the facets
    if len(products) == 0:
        facets = []
    else:
        # Get facets from the results
        facets = results.get_facets() if results.get_facets() else []

    timeelapsed = time.time() - starttime  

    
    # check products and facets to be of json format
    if isinstance(products, list):
        products = [dict(product) for product in products if product is not None]
    if isinstance(facets, list):
        facets = [dict(facet) for facet in facets if facet is not None]

    total_count = results.get_count() if results.get_count() else 0

    

    return render_template('index.html', products=products, q=search_query, q2=rewritten_query, p=profile, t=searchtype, i=items, s=sortby, timeelapsed=timeelapsed, facets=facets,debug_info=debug_search_args,total_count=total_count, debug_search_args=debug_search_args)
    
if __name__ == '__main__':  
    app.run(debug=True)