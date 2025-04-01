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
  
app = Flask(__name__)  
  
# Load environment variables  
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
    prompt = f"Rewrite the following query as simple product search query. Output should include few words, no verbs, no full sentence. Keep original language same. Query: {search_query}"  
    response = client.chat.completions.create(  
        messages=[{"role": "user", "content": prompt}],  
        model=os.environ.get('azure_openai_model'),  
        max_tokens=50,  
        temperature=0.5,  
    )  
    rewritten_query = response.choices[0].message.content.strip()  
    return rewritten_query  
  
def product_search_vector(search_query, num_results=50, category=None, price_range=None, gender=None):  
    vector_query = VectorizableTextQuery(  
        text=search_query,  
        k_nearest_neighbors=50,  
        fields="descriptionEmbedding,nameEmbedding,tagEmbedding"  
    )  
    filter_query = f"categories/any(s: s eq '{category}')" if category else None  
    results = search_client.search(  
        search_text=None,  
        vector_queries=[vector_query],  
        top=num_results,  
        vector_filter_mode=VectorFilterMode.PRE_FILTER,  
        select=["productId", "name", "description", "imageUrl"],  
        filter=filter_query,  
    )  
    results_list = [result for result in results][:num_results]  
    return results_list  
  
def product_search_keyword(search_query, num_results=50, category=None, price_range=None, gender=None):  
    filter_query = f"categories/any(s: s eq '{category}')" if category else None  
    results = search_client.search(  
        search_text=search_query,  
        top=num_results,  
        select=["productId", "name", "description", "imageUrl"],  
        filter=filter_query,  
    )  
    results_list = [result for result in results][:num_results]  
    return results_list  
  
@app.route('/', methods=['GET', 'POST'])  
def index():  
    starttime = time.time()  
    if request.method == 'POST':  
        search_query = request.form.get('search_query')  
        category = request.form.get('category', '')  
        gender = request.form.get('gender', None)  
        sortby = request.form.get('sortby', 'default')  
        searchtype = request.form.get('searchtype', 'keyword')  
        items = int(request.form.get('items', 20))  
        return redirect(url_for('index', q=search_query, c=category, t=searchtype, g=gender, i=items, s=sortby))  
    else:   
        search_query = request.args.get('q', '')  
        category = request.args.get('c', '')  
        gender = request.args.get('g', None)  
        sortby = request.args.get('s', 'default')  
        searchtype = request.args.get('t', 'keyword')  
        items = int(request.args.get('i', 20))
        filter_query = request.args.get('f', None)
  
    results = []  
    rewritten_query = ''  
    if searchtype == 'keyword':  
        if filter_query:
            filters = []
            for filter_item in filter_query.split(','):
                category, values = filter_item.split(':')
                values = values.replace('%20', ' ').split('|')  # Handle URL-encoded spaces and split values
                
                # Check if the field is a collection or not
                if category in ["categories", "tags"]:  # Example of collection fields
                    filters.append(f"{category}/any(s: s eq '{' or s eq '.join(values)}')")
                else:  # For non-collection fields
                    filters.append(f"({category} eq '{' or '.join(values)}')")

            filter_query = ' and '.join(filters)
        else:
            filter_query = f"categories/any(s: s eq '{category}')" if category else None

        # Perform the search
        results = search_client.search(  
            search_text=search_query,  
            top=items,  
            select=["productId", "name", "description", "imageUrl"],  
            filter=filter_query,  
            facets=["brandName", "genderName", "colorName", "mainCategoryName", "rating"]  
        )
    elif searchtype == 'vector':  
        vector_query = VectorizableTextQuery(  
            text=search_query,  
            k_nearest_neighbors=50,  
            fields="descriptionEmbedding,nameEmbedding,tagEmbedding"  
        )  
        filter_query = f"categories/any(s: s eq '{category}')" if category else None  
        results = search_client.search(  
            search_text=None,  
            vector_queries=[vector_query],  
            top=items,  
            vector_filter_mode=VectorFilterMode.PRE_FILTER,  
            select=["productId", "name", "description", "imageUrl"],  
            filter=filter_query,  
            facets=["brandName", "genderName", "colorName", "mainCategoryName", "rating"]  
        )  
    elif searchtype == 'rewrite':  
        rewritten_query = rewrite_search_query(search_query)  
        vector_query = VectorizableTextQuery(  
            text=rewritten_query,  
            k_nearest_neighbors=50,  
            fields="descriptionEmbedding,nameEmbedding,tagEmbedding"  
        )  
        filter_query = f"categories/any(s: s eq '{category}')" if category else None  
        results = search_client.search(  
            search_text=None,  
            vector_queries=[vector_query],  
            top=items,  
            vector_filter_mode=VectorFilterMode.PRE_FILTER,  
            select=["productId", "name", "description", "imageUrl"],  
            filter=filter_query,  
            facets=["brandName", "genderName", "colorName", "mainCategoryName", "rating"]  
        )  
    elif searchtype == 'custom1':  
        vector_query = VectorizableTextQuery(  
            text=search_query,  
            k_nearest_neighbors=50,  
            fields="descriptionEmbedding,nameEmbedding,tagEmbedding"  
        )  
        filter_query = f"genderName eq 'Kadın'" if gender else None  
        results = search_client.search(  
            search_text=None,  
            vector_queries=[vector_query],  
            top=items,  
            vector_filter_mode=VectorFilterMode.PRE_FILTER,  
            select=["productId", "name", "description", "imageUrl"],  
            filter=filter_query,  
            facets=["brandName", "genderName", "colorName", "mainCategoryName", "rating"]  
        )  
    elif searchtype == 'custom2':  
        vector_query = VectorizableTextQuery(  
            text=search_query,  
            k_nearest_neighbors=50,  
            fields="descriptionEmbedding,nameEmbedding,tagEmbedding"  
        )  
        filter_query = f"genderName eq '{gender}'" if gender else None  
        results = search_client.search(  
            search_text=None,  
            vector_queries=[vector_query],  
            top=items,  
            vector_filter_mode=VectorFilterMode.PRE_FILTER,  
            select=["productId", "name", "description", "imageUrl"],  
            filter=filter_query,  
            facets=["brandName", "genderName", "colorName", "mainCategoryName", "rating"]  
        )  
  
    products = [result for result in results]  

    facets = results.get_facets()

    timeelapsed = time.time() - starttime  
  
    return render_template('index.html', products=products, q=search_query, q2=rewritten_query, c=category, g=gender, t=searchtype, i=items, s=sortby, timeelapsed=timeelapsed, facets=facets)  
  
    
if __name__ == '__main__':  
    app.run(debug=True)  