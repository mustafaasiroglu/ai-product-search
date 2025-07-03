from flask import Flask, request, render_template, redirect, url_for  
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

    
def get_synonymmap(synonymmap_name: str) -> Dict:
    url = f"{search_endpoint}/synonymmaps('{synonymmap_name}')?api-version={search_api_version}"
    headers = {
        "api-key": search_key
    }

    try:
        response = requests.get(url, headers=headers)
        return response.json()
    except requests.exceptions.RequestException as e:
        raise Exception(f"Synonym map request failed: {str(e.response)}") from e
    

def put_synonymmap(name: str, synonyms: list[str], format: str = "solr"):
    url = f"{search_endpoint}/synonymmaps/{name}?api-version={search_api_version}"
    headers = {"Content-Type": "application/json","api-key": search_key}
    body = {
        "name": name,
        "format": format,
        "synonyms": ("\n").join(synonyms)
    }
    try:
        response = requests.put(url, headers=headers, json=body)
        response.raise_for_status()  # Raise exception for bad status codes
    except requests.exceptions.RequestException as e:
        # Handle request exceptions
        detail = e.response.json().get("error", {}).get("message", str(e))
        raise Exception(f"Synonym map request failed: {str(e)+ ' ' + detail}") from e
    return response


def update_boyner_synonymmap() -> None:
    csv_file_path = "synonyms.csv"
    synonyms = []
    with open(csv_file_path, "r", encoding="utf-8") as file:
        synonymlines = [line.strip().split("|") for line in file.readlines() if line.strip()]
    
    for line in synonymlines:
        if line[0] == "merge":
            synonyms.append(line[2]+","+line[1])
        elif line[0] == "replace":
            synonyms.append(line[1]+" => "+line[2])
    synonymmap_name = "boyner"
    put_synonymmap(synonymmap_name, synonyms)
    ##print(get_synonymmap("boyner"))

def get_index_schema() -> None:
    url = f"{search_endpoint}/indexes/{search_index}?api-version={search_api_version}"
    headers = {
        "api-key": search_key
    }
    try:
        response = requests.get(url, headers=headers)
        return response.json()
    except requests.exceptions.RequestException as e:
        raise Exception(f"Index schema request failed: {str(e.response)}") from e
    
def update_index_schema(schemajson) -> None:
    url = f"{search_endpoint}/indexes/{search_index}?api-version={search_api_version}"
    headers = {
        "Content-Type": "application/json",
        "api-key": search_key
    }
    body = schemajson
    try:
        response = requests.put(url, headers=headers, json=body)
        response.raise_for_status()  # Raise exception for bad status codes
    except requests.exceptions.RequestException as e:
        # Handle request exceptions
        detail = e.response.json().get("error", {}).get("message", str(e))
        raise Exception(f"Index schema request failed: {str(e)+ ' ' + detail}") from e
    return response

if __name__ == '__main__':  

    x = get_index_schema()
    # x["suggesters"] = [
    #     {
    #     "name": "sg",
    #     "searchMode": "analyzingInfixMatching",
    #     "sourceFields": ["brandName","mainCategoryName"]
    #     }
    # ]
    # update_index_schema(x)

    pretty_print = json.dumps(get_index_schema(), indent=4)
    
    print(pretty_print)