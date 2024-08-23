# Add the parent directory of 'backend' to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.insert(0, parent_dir)


import os
import sys
import uuid

from azure.cosmos import CosmosClient, PartitionKey, exceptions
from azure.identity import AzureCliCredential
from azure.storage.blob import BlobServiceClient

import backend.src.api.common as common

# REQUIRES BOTH of the following environment variables to be set:
# - STORAGE_ACCOUNT_BLOB_URL
# - COSMOS_URI_ENDPOINT


def _upload_files(blob_service_client, source_directory, container_name):
    container_client = blob_service_client.get_container_client(container_name)
    for root, _, files in os.walk(source_directory):
        for file in files:
            file_path = os.path.join(root, file)
            blob_name = os.path.relpath(file_path, source_directory)
            with open(file_path, "rb") as data:
                container_client.upload_blob(name=blob_name, data=data)


def prepare_valid_index_data(source_data_dir, index_dir, prefix):
    """Prepare valid data by uploading the result files of a "valid" indexing run to a new blob container."""
    account_url = os.environ["STORAGE_ACCOUNT_BLOB_URL"]
    # print(f"Uploading data to: {account_url}")
    credential = AzureCliCredential()
    # print(f"Using credential: {credential.get_token('https://storage.azure.com/.default')}")
    blob_service_client = BlobServiceClient(account_url, credential=credential)
    # print(f"Using blob service client: {blob_service_client}")

    # Generate a unique data container name
    container_name = f"{prefix}-data-{str(uuid.uuid4())}"
    container_name = container_name.replace("_", "-").replace(".", "-").lower()[:63]
    container_name_sanitized = common.sanitize_name(container_name)

    try:
        blob_service_client.create_container(container_name_sanitized)
    except Exception as e:
        print(f"Error creating container: {e}")
        sys.exit(1)

    # Generate a unique index container name
    index_name = f"{prefix}-idx-{str(uuid.uuid4())}"
    index_name = index_name.replace("_", "-").replace(".", "-").lower()[:63]
    index_name_sanitized = common.sanitize_name(index_name)
    blob_service_client.create_container(index_name_sanitized)

    # Upload files from the source data directory
    _upload_files(blob_service_client, source_data_dir, container_name_sanitized)

    # Upload files from the index directory
    _upload_files(blob_service_client, index_dir, index_name_sanitized)

    print(f"Data uploaded to container: {container_name} - {container_name_sanitized}")
    print(f"Index uploaded to container: {index_name} - {index_name_sanitized}")

    # ------------------------------------

    endpoint = os.environ["COSMOS_URI_ENDPOINT"]
    print(f"Using Cosmos DB endpoint: {endpoint}")
    client = CosmosClient(endpoint, credential)

    database_name = "graphrag"
    database = client.get_database_client(database_name)

    container_store = "container-store"
    try:
        container_container = database.get_container_client(container_store)
        container_container.read()
    except Exception:
        database.create_container(
            id=container_store, partition_key=PartitionKey(path="/id")
        )
        container_container = database.get_container_client(container_store)

    container_container.upsert_item(
        {
            "id": container_name_sanitized,
            "human_readable_name": container_name,
            "type": "data",
        }
    )
    container_container.upsert_item(
        {
            "id": index_name_sanitized,
            "human_readable_name": index_name,
            "type": "index",
        }
    )

    container_store = "jobs"

    try:
        container_jobs = database.get_container_client(container_store)
        container_jobs.read()
    except exceptions.CosmosResourceNotFoundError:
        database.create_container(
            id=container_store, partition_key=PartitionKey(path="/id")
        )
        container_jobs = database.get_container_client(container_store)

    index_item = {
        "id": index_name_sanitized,
        "sanitized_index_name": index_name_sanitized,
        "human_readable_index_name": index_name,
        "sanitized_storage_name": container_name_sanitized,
        "human_readable_storage_name": container_name,
        "all_workflows": [
            "create_base_text_units",
            "create_final_text_units",
            "create_base_extracted_entities",
            "create_summarized_entities",
            "create_base_entity_graph",
            "create_final_entities",
            "create_final_relationships",
            "create_base_documents",
            "create_base_document_graph",
            "create_final_documents",
            "create_final_communities",
            "create_final_community_reports",
            "create_final_covariates",
            "create_base_entity_nodes",
            "create_base_document_nodes",
            "create_final_nodes",
        ],
        "completed_workflows": [
            "create_base_text_units",
            "create_base_extracted_entities",
            "create_final_covariates",
            "create_summarized_entities",
            "create_base_entity_graph",
            "create_final_entities",
            "create_final_relationships",
            "create_final_communities",
            "create_final_community_reports",
            "create_base_entity_nodes",
            "create_final_text_units",
            "create_base_documents",
            "create_base_document_graph",
            "create_base_document_nodes",
            "create_final_documents",
            "create_final_nodes",
        ],
        "failed_workflows": [],
        "status": "complete",
        "percent_complete": 100,
        "progress": "16 out of 16 workflows completed successfully.",
        "entity_extraction_prompt": "UNK",
        "community_report_prompt": "UNK",
        "summarize_descriptions_prompt": "UNK",
    }
    container_jobs.create_item(body=index_item)


if __name__ == "__main__":
    print(
        "Note: Currently logged in user must be able to access the resources in the deployment rg network."
    )

    if len(sys.argv) != 4:
        print(
            "Usage: python script.py <source_data_directory> <index_directory> <prefix>"
        )
        sys.exit(1)

    source_data_dir = sys.argv[1]
    index_dir = sys.argv[2]
    prefix = sys.argv[3]

    prepare_valid_index_data(source_data_dir, index_dir, prefix)
