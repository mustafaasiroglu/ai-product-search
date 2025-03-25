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

def rewrite_search_query(search_query):
    client = AzureOpenAI(
        azure_deployment=os.environ['azure_openai_deployment'],
        api_version=os.environ['azure_openai_api_version'],
        azure_endpoint=os.environ['azure_openai_endpoint'],
        api_key=os.environ['azure_openai_key'],
    )
    prompt = f"Rewrite the following query as simple product search query. Output should include few words, no verbs, no full sentence. keep original language same. Query: {search_query}"
    response = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model=os.environ['azure_openai_model'],
        max_tokens=50,
        temperature=0.5,
    )
    rewritten_query = response.choices[0].message.content.strip()
    return rewritten_query

def product_search_vector(search_query, num_results=50, category=None, price_range=None):

    search_endpoint = os.environ['search_endpoint']
    search_key = os.environ['search_key']
    search_index = os.environ['search_index']

    search_client = SearchClient(endpoint=search_endpoint,
                                 index_name=search_index,
                                 credential=AzureKeyCredential(search_key))
    
    vector_query = VectorizableTextQuery(text=search_query, k_nearest_neighbors=50, fields="text_vector")
    
    results = search_client.search(search_text=None,
                                   vector_queries= [vector_query],
                                   top=num_results, 
                                   vector_filter_mode=VectorFilterMode.PRE_FILTER,
                                   select=["product_id","name","description","image_url","image_description"],
                                   filter= f"categories/any(s: s eq '{category}')" if category else None,
                                   )

    results_list = [result for result in results][:num_results]
    
    return results_list

def product_search_keyword(search_query, num_results=50, category=None, price_range=None):

    search_endpoint = os.environ['search_endpoint']
    search_key = os.environ.get("search_key")
    search_index = os.environ.get("search_index")

    search_client = SearchClient(endpoint=search_endpoint,
                                 index_name=search_index,
                                 credential=AzureKeyCredential(search_key))
    
    results = search_client.search(search_query,
                                   top=num_results, 
                                   select=["product_id","name","description","image_url","image_description"],
                                   filter= f"categories/any(s: s eq '{category}')" if category else None,
                                   )

    results_list = [result for result in results][:num_results]
    
    return results_list

@app.route('/', methods=['GET', 'POST'])
def index():

    starttime = time.time()

    if request.method == 'POST':
        search_query = request.form.get('search_query')
        category = request.form.get('category', '')
        searchtype = request.form.get('searchtype', 'vector')
        items = int(request.form.get('items', 20))
        return redirect(url_for('index', q=search_query, c=category, t=searchtype))
    else:
        search_query = request.args.get('q', '')
        category = request.args.get('c', '')
        searchtype = request.args.get('t', 'vector')
        items = int(request.args.get('i', 20))

    products = []
    rewritten_query = ''

    if searchtype == 'vector':
        products = product_search_vector(search_query, items, category)
    elif searchtype == 'rewrite':
        rewritten_query = rewrite_search_query(search_query)
        products = product_search_vector(rewritten_query, items, category)
    else:
        products = product_search_keyword(search_query, items, category)

    timeelapsed = time.time() - starttime
    print(f"Time elapsed: {timeelapsed} seconds")

    return render_template('index.html', products=products, q=search_query, q2=rewritten_query, c=category, t=searchtype, i=items, timeelapsed=timeelapsed)


if __name__ == '__main__':
    app.run(debug=True)