from flask import Flask, request, render_template, redirect, url_for
import psycopg2
from get_conn import get_connection_uri

app = Flask(__name__)

def product_search(search_query, num_results, category=None, price_range=None):
    conn_string = get_connection_uri()
    conn = psycopg2.connect(conn_string)
    cursor = conn.cursor()

    # Define the SQL function as a string
    sql_function = '''
    drop function if exists product_search(text, text, int);
    create function
        product_search(searchQuery text, category text, numResults int)
    returns table(
                product_id text,
                name text,
                description text,
                image_url text,
                image_description text,
                score real)
    as $$
    declare
        query_embedding vector(1536);
    begin
        query_embedding := (azure_openai.create_embeddings('text-embedding-ada-002', searchQuery));
        return query
        select
            p.product_id::text,
            p.name::text,
            p.description::text,
            p.image_url::text,
            p.image_description::text,
            (p.embedding <=> query_embedding)::real as score
        from
            products p
        where
            p.embedding is not null
        and
            (category = '' or p.categories ? category)
       
        order by score asc limit numResults; -- cosine distance
    end $$
    language plpgsql;
    '''

    # Execute the SQL function
    cursor.execute(sql_function)
    conn.commit()

    edited_query = "*" if search_query == "" else search_query
    # Call the function with parameters
    cursor.callproc('product_search', (edited_query,category, num_results))
    results = cursor.fetchall()

    # Close the connection
    cursor.close()
    conn.close()
    sorted_results = sorted(results, key=lambda x: x[5])
    return sorted_results

def product_search_keyword(search_query, num_results, category=None, price_range=None):
    conn_string = get_connection_uri()
    conn = psycopg2.connect(conn_string)
    cursor = conn.cursor()

    # Define the SQL function as a string
    sql_function = '''
    drop function if exists product_search_keyword(text, text, int);
    create function
        product_search_keyword(searchQuery text, category text, numResults int)
    returns table(
                product_id text,
                name text,
                description text,
                image_url text,
                image_description text,
                score real
                )
    as $$
    begin
        return query
        select
            p.product_id::text,
            p.name::text,
            p.description::text,
            p.image_url::text,
            p.image_description::text,
            0.00000::real as score
        from
            products p
        where
            (category = '' or p.categories ? category)
        and
            (searchQuery = '' or p.name ilike '%' || searchQuery || '%' or p.description ilike '%' || searchQuery || '%' or p.image_description ilike '%' || searchQuery || '%' )
        order by score asc limit numResults; -- cosine distance
    end $$
    language plpgsql;
    '''

    # Execute the SQL function
    cursor.execute(sql_function)
    conn.commit()

    edited_query = "" if search_query == "" else search_query
    # Call the function with parameters
    cursor.callproc('product_search_keyword', (edited_query,category, num_results))
    results = cursor.fetchall()

    # Close the connection
    cursor.close()
    conn.close()
    return results

@app.route('/', methods=['GET', 'POST'])
def index():

    if request.method == 'POST':
        search_query = request.form.get('search_query')
        category = request.form.get('category', '')
        searchtype = request.form.get('searchtype', 'vector')
        items = request.form.get('items', 20)
        return redirect(url_for('index', q=search_query, c=category, t=searchtype))
    else:
        search_query = request.args.get('q', '')
        category = request.args.get('c', '')
        searchtype = request.args.get('t', 'vector')
        items = request.args.get('i', 20)

    products = []

    if searchtype == 'vector':
        products = product_search(search_query, items, category)
    else:
        products = product_search_keyword(search_query, items, category)

    return render_template('index.html', products=products, q=search_query, c=category, t=searchtype, i=items)

@app.route('/api/search', methods=['GET'])
def api_search(q='', c='', t='vector', i=20):
    search_query = request.args.get('q', q)
    category = request.args.get('c', c)
    searchtype = request.args.get('t', t)
    items = request.args.get('items', i)
    products = []

    if searchtype == 'vector':
        products = product_search(search_query, items, category)
    else:
        products = product_search_keyword(search_query, items, category)
    
    for i in range(len(products)):
        description = ' '.join(products[i][2].split()).strip()
        products[i] = {
            'product_id': products[i][0],
            'product_title': products[i][1],
            'description': description,
            'image_url': "https://statics.boyner.com.tr/mnresize/505/704/productimages/"+products[i][3],
            'image_description': products[i][4],
            'score': products[i][5]
        }

    return {'results': products}

if __name__ == '__main__':
    app.run(debug=True)