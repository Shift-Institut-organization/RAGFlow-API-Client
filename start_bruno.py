import sys
from pathlib import Path

# Ensure src/ is in sys.path
sys.path.insert(0, str((Path(__file__).parent / "src").resolve()))

from bruno_populator.config import BrunoRunConfig
from bruno_populator.runner import run_bruno_collection

if __name__ == "__main__":
    if "--sync-tokens" in sys.argv:
        from bruno_populator.yml_injector import sync_all_collection_tokens

        updated = sync_all_collection_tokens()
        print(f"Synced API token across {len(updated)} collection(s).")
        sys.exit(0)

    if "--clear-tokens" in sys.argv:
        from bruno_populator.yml_injector import clear_all_collection_tokens

        cleared = clear_all_collection_tokens()
        print(f"Cleared API token from {len(cleared)} collection(s).")
        sys.exit(0)

    col_dir = Path("bruno/RAGFlowApiClient/collections/Dev API Calls").resolve()
    config = BrunoRunConfig(
        collection_dir=col_dir,
        request_file="Session.yml",
        env=None,
        output_json_path=col_dir / "output.json",
    )
    result = run_bruno_collection(config)
    print(f"Bruno single request execution finished. Result loaded: {bool(result)}")
