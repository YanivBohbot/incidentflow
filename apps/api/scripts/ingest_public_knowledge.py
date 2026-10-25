"""Load official public documentation with LangChain and index it in Pinecone on explicit commit."""

import argparse

from incidentflow.core.config import get_settings
from incidentflow.knowledge.official_sources import load_official_knowledge_sources
from incidentflow.knowledge.pinecone_store import PineconeKnowledgeStore, split_documents


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Write vectors to Pinecone. Without this flag, only fetch and split documents.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete and replace only the configured Pinecone namespace before indexing.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.replace and not args.commit:
        raise SystemExit("--replace requires --commit because it deletes the configured namespace.")

    documents = load_official_knowledge_sources()
    chunks = split_documents(documents)
    print(f"Loaded {len(documents)} official documents and produced {len(chunks)} chunks.")

    if not args.commit:
        print("Dry run complete. Re-run with --commit to write the chunks to Pinecone.")
        return 0

    settings = get_settings()
    store = PineconeKnowledgeStore.from_settings(
        settings,
        namespaces=(settings.pinecone_namespace,),
    )
    ids = store.replace_documents(chunks) if args.replace else store.add_documents(chunks)
    action = "Replaced" if args.replace else "Indexed"
    print(
        f"{action} {len(ids)} chunks in {settings.pinecone_index_name}/{settings.pinecone_namespace}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
