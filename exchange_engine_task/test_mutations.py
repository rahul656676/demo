import os
import subprocess
import shutil

mutations = [
    {
        "name": "Remove Iceberg Priority Loss",
        "search": "o.priority_id = new_p_id",
        "replace": "# o.priority_id = new_p_id"
    },
    {
        "name": "Modify Maker into Taker charges 0 fees",
        "search": "if not is_auction:",
        "replace": "if False: # not is_auction:"
    },
    {
        "name": "Trade Bust applies product multiplier (no sequential floor)",
        "search": "math.floor(trade.qty * action_value)",
        "replace": "trade.qty * action_value"
    },
    {
        "name": "Remove Tick-Size Rounding (Floor to 0) on Dividends",
        "search": "order.price = max(0, order.price - amount)",
        "replace": "order.price -= amount"
    }
]

def run_mutation(m):
    print(f"Testing mutation: {m['name']}")
    with open("oracle.py", "r") as f:
        code = f.read()
    
    if m["search"] not in code:
        print("  [ERROR] Search string not found in oracle.py")
        return False
        
    mutated_code = code.replace(m["search"], m["replace"])
    with open("oracle_mutated.py", "w") as f:
        f.write(mutated_code)
        
    # Run oracle
    res = subprocess.run(["python", "oracle_mutated.py", "events.jsonl", "mutated_ledger.json"], capture_output=True)
    if res.returncode != 0:
        print("  [PASS] Mutated oracle crashed")
        return True
        
    # Run verifier
    res = subprocess.run(["python", "verifier.py", "mutated_ledger.json", "ledger.json"], capture_output=True)
    if res.returncode != 0:
        print("  [PASS] Verifier failed (mutation caught)")
        return True
    else:
        print("  [FAIL] Verifier passed (mutation survived!)")
        return False

def main():
    survived = 0
    for m in mutations:
        if not run_mutation(m):
            survived += 1
    
    if survived == 0:
        print("ALL MUTATIONS KILLED")
    else:
        print(f"{survived} MUTATIONS SURVIVED")

if __name__ == "__main__":
    main()
