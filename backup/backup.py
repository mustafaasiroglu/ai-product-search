from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.core.credentials import AzureKeyCredential
import os, json

load_dotenv(override=True) # take environment variables from .env.

# Variables not used here do not need to be updated in your .env file
source_endpoint = "https://ai-search-bynr-data-prod-szn-01.search.windows.net"
source_credential = AzureKeyCredential("B8HL7g4KI1HcOFvSB81bgov5X2z2jNXLRhZBYq4Z8aAzSeAEZQ3y")
source_index_name =  "boyner-products"

from azure.search.documents import SearchClient  
from azure.search.documents.indexes import SearchIndexClient
import tqdm  
  
def create_clients(endpoint, credential, index_name):  
    search_client = SearchClient(endpoint=endpoint, index_name=index_name, credential=credential)  
    index_client = SearchIndexClient(endpoint=endpoint, credential=credential)  
    return search_client, index_client

def total_count(search_client):
    response = search_client.search(include_total_count=True, search_text="*", top=0)
    return response.get_count()
  
def search_results_with_filter(search_client, key_field_name):
    last_item = None
    response = search_client.search(search_text="*", top=100000, order_by=key_field_name).by_page()
    while True:
        for page in response:
            page = list(page)
            if len(page) > 0:
                last_item = page[-1]
                yield page
            else:
                last_item = None
        
        if last_item:
            response = search_client.search(search_text="*", top=100000, order_by=key_field_name, filter=f"{key_field_name} gt '{last_item[key_field_name]}'").by_page()
        else:
            break

def search_results_without_filter(search_client):
    response = search_client.search(search_text="*", top=100000).by_page()
    for page in response:
        page = list(page)
        yield page

def backup_and_restore_index(source_endpoint, source_key, source_index_name):  
    # Create search and index clients  
    source_search_client, source_index_client = create_clients(source_endpoint, source_key, source_index_name)  
  
    # Get the source index definition  
    source_index = source_index_client.get_index(name=source_index_name)
    non_retrievable_fields = []
    for field in source_index.fields:
        if field.hidden == True:
            non_retrievable_fields.append(field)
        if field.key == True:
            key_field = field

    if not key_field:
        raise Exception("Key Field Not Found")
    
    if len(non_retrievable_fields) > 0:
        print(f"WARNING: The following fields are not marked as retrievable and cannot be backed up and restored: {', '.join(f.name for f in non_retrievable_fields)}")
  
  
    document_count = total_count(source_search_client)
    can_use_filter = key_field.sortable and key_field.filterable
    if not can_use_filter:
        print("WARNING: The key field is not filterable or not sortable. A maximum of 100,000 records can be backed up and restored.")
    # Backup and restore documents  
    all_documents = search_results_with_filter(source_search_client, key_field.name) if can_use_filter else search_results_without_filter(source_search_client)

    print("Backing up and restoring documents:")  
    failed_documents = 0  
    failed_keys = []  
    with tqdm.tqdm(total=document_count) as progress_bar:  
        for page in all_documents:
            # save page to json file
            with open(f"backup/documents/document_{page[0][key_field.name]}.json", "w") as json_file:
                json.dump(page, json_file)
            # Upload documents to target index
            
  
    print(f"Successfully backed up '{source_index_name}'")  
    return source_search_client, all_documents


source_search_client, all_documents = backup_and_restore_index(source_endpoint, source_credential, source_index_name) 