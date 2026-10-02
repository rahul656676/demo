import json
import sys

def main():
    if len(sys.argv) != 3:
        print("Usage: python verifier.py <candidate_ledger.json> <expected_ledger.json>")
        sys.exit(1)
        
    try:
        with open(sys.argv[1], 'r') as f:
            candidate = json.load(f)
    except Exception as e:
        print(f"Error loading candidate JSON: {e}")
        sys.exit(1)
        
    try:
        with open(sys.argv[2], 'r') as f:
            expected = json.load(f)
    except Exception as e:
        print(f"Error loading expected JSON: {e}")
        sys.exit(1)

    if candidate == expected:
        print("PASS")
        sys.exit(0)
    else:
        print("FAIL: Ledgers mismatch.")
        sys.exit(1)

if __name__ == "__main__":
    main()
