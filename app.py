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

search_endpoint = os.environ['search_endpoint']
search_key = os.environ['search_key']
search_index = os.environ['search_index']
search_client = SearchClient(endpoint=search_endpoint,
                                 index_name=search_index,
                                 credential=AzureKeyCredential(search_key))


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

def product_search_vector(search_query, num_results=50, category=None, price_range=None, gender=None):

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
                                   select=["productId","name","description","imageUrl","description"],
                                   filter= f"categories/any(s: s eq '{category}')" if category else None,
                                   )

    results_list = [result for result in results][:num_results]
    
    return results_list

def product_search_keyword(search_query, num_results=50, category=None, price_range=None, gender=None):

    search_endpoint = os.environ['search_endpoint']
    search_key = os.environ.get("search_key")
    search_index = os.environ.get("search_index")

    search_client = SearchClient(endpoint=search_endpoint,
                                 index_name=search_index,
                                 credential=AzureKeyCredential(search_key))
    
    results = search_client.search(search_query,
                                   top=num_results, 
                                   select=["productId","name","description","imageUrl","description"],
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
        gender = request.form.get('gender', None)
        sortby = request.form.get('sortby', 'default')
        searchtype = request.form.get('searchtype', 'keyword')
        items = int(request.form.get('items', 20))
        return redirect(url_for('index', q=search_query, c=category, t=searchtype))
    else:
        search_query = request.args.get('q', '')
        category = request.args.get('c', '')
        gender = request.args.get('g', None)
        sortby = request.args.get('s', 'default')
        searchtype = request.args.get('t', 'keyword')
        items = int(request.args.get('i', 20))

    results = []
    rewritten_query = ''

    if searchtype == 'keyword':
        results = search_client.search(search_query,
                                   top=items, 
                                   select=["productId","name","description","imageUrl","description"],
                                   filter= f"categories/any(s: s eq '{category}')" if category else None,
                                   )
        
    elif searchtype == 'vector':
        vector_query = VectorizableTextQuery(text=search_query, k_nearest_neighbors=50, fields="text_vector")
        results = search_client.search(search_text=search_query,
                                    vector_queries= [vector_query],
                                    top=items, 
                                    vector_filter_mode=VectorFilterMode.PRE_FILTER,
                                    select=["productId","name","description","imageUrl","description"],
                                    filter= f"categories/any(s: s eq '{category}')" if category else None,
                                    )
        

    elif searchtype == 'rewrite':
        rewritten_query = rewrite_search_query(search_query)
        vector_query = VectorizableTextQuery(text=rewritten_query, k_nearest_neighbors=50, fields="text_vector")
        results = search_client.search(search_text=search_query,
                                    vector_queries= [vector_query],
                                    top=items, 
                                    vector_filter_mode=VectorFilterMode.PRE_FILTER,
                                    select=["productId","name","description","imageUrl","description"],
                                    filter= f"categories/any(s: s eq '{category}')" if category else None,
                                    )
        
    elif searchtype == 'custom1':
        vector_query = VectorizableTextQuery(text=search_query, k_nearest_neighbors=50, fields="text_vector")
        results = search_client.search(search_text=search_query,
                                    vector_queries= [vector_query],
                                    top=items, 
                                    vector_filter_mode=VectorFilterMode.PRE_FILTER,
                                    select=["productId","name","description","imageUrl","description"],
                                    filter= f"genderName eq 'Kadın'" if gender else None,
                                    # scoring_profile="custom1",
                                    )
    
    elif searchtype == 'custom2':
        vector_query = VectorizableTextQuery(text=search_query, k_nearest_neighbors=50, fields="text_vector")
        if gender is "":
            results = search_client.search(search_text=search_query,
                                   top=items, 
                                   select=["productId","name","description","imageUrl","description"],
                                   )
        else:
                results = search_client.search(search_text=search_query,
                                   top=items, 
                                   select=["productId","name","description","imageUrl","description"],
                                   filter= f"genderName eq '{gender}'",
                                   )
    
    products = [result for result in results]

    timeelapsed = time.time() - starttime

    return render_template('index.html', products=products, q=search_query, q2=rewritten_query, c=category, g=gender, t=searchtype, i=items, s=sortby, timeelapsed=timeelapsed)


if __name__ == '__main__':
    app.run(debug=True)