"""Load local PDF, Markdown, and text sources into the isolated IncidentFlow namespace."""

import argparse
from pathlib import Path

from incidentflow.core.config import get_settings
from incidentflow.knowledge.local_sources import load_local_knowledge_sources
from incidentflow.knowledge.pinecone_store import PineconeKnowledgeStore, split_documents

DEFAULT_SOURCE_DIR = Path(__file__).resolve().parents[1] / "knowledge_sources"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="Directory containing English .pdf, .md, and .txt files.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Write vectors to Pinecone. Without this flag, only load and split documents.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete and replace only the local IncidentFlow namespace before indexing.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.replace and not args.commit:
        raise SystemExit("--replace requires --commit because it deletes the local namespace.")

    source_dir = args.source_dir.resolve()
    documents = load_local_knowledge_sources(source_dir)
    chunks = split_documents(documents)
    print(f"Loaded {len(documents)} local documents and produced {len(chunks)} chunks.")
    if not chunks:
        print(f"No supported source files found in {source_dir}.")
        return 0

    if not args.commit:
        print("Dry run complete. Re-run with --commit to write the chunks to Pinecone.")
        return 0

    settings = get_settings()
    store = PineconeKnowledgeStore.from_settings(
        settings,
        namespaces=(settings.pinecone_local_namespace,),
    )
    ids = store.replace_documents(chunks) if args.replace else store.add_documents(chunks)
    action = "Replaced" if args.replace else "Indexed"
    print(
        f"{action} {len(ids)} chunks in "
        f"{settings.pinecone_index_name}/{settings.pinecone_local_namespace}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
