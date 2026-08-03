import json
import random
import sys

def main():
    if len(sys.argv) != 2:
        sys.exit(1)
        
    random.seed(42)
    firms = [f"FIRM_{i}" for i in range(1, 21)]
    symbols = [f"SYM_{i}" for i in range(1, 6)]
    
    events = []
    seq_id = 1
    order_id = 1
    
    def add_event(ev):
        nonlocal seq_id
        ev['sequence_id'] = seq_id
        events.append(ev)
        seq_id += 1

    # Pattern 1: Infinite Foundation
    for sym in symbols:
        # Pre-market state
        add_event({"type": "SESSION_CHANGE", "action_value": "PRE_MARKET", "symbol": sym})
        
        for firm in firms:
            # Deep out of money limits
            for _ in range(5):
                add_event({"type": "NEW_ORDER", "order_id": order_id, "firm_id": firm, "symbol": sym, "side": "BUY", "order_type": "LIMIT", "price": random.randint(100, 500), "qty": random.randint(10, 50)})
                order_id += 1
                add_event({"type": "NEW_ORDER", "order_id": order_id, "firm_id": firm, "symbol": sym, "side": "SELL", "order_type": "LIMIT", "price": random.randint(1500, 2000), "qty": random.randint(10, 50)})
                order_id += 1
            
            # Icebergs
            add_event({"type": "NEW_ORDER", "order_id": order_id, "firm_id": firm, "symbol": sym, "side": "BUY", "order_type": "ICEBERG", "price": random.randint(500, 900), "qty": 100, "visible_qty": 10})
            order_id += 1
            add_event({"type": "NEW_ORDER", "order_id": order_id, "firm_id": firm, "symbol": sym, "side": "SELL", "order_type": "ICEBERG", "price": random.randint(1100, 1500), "qty": 100, "visible_qty": 10})
            order_id += 1
            
            # Pegged
            add_event({"type": "NEW_ORDER", "order_id": order_id, "firm_id": firm, "symbol": sym, "side": "BUY", "order_type": "PEGGED", "peg_offset": -10, "qty": 50})
            order_id += 1
            add_event({"type": "NEW_ORDER", "order_id": order_id, "firm_id": firm, "symbol": sym, "side": "SELL", "order_type": "PEGGED", "peg_offset": 10, "qty": 50})
            order_id += 1
            
        # Auction
        add_event({"type": "SESSION_CHANGE", "action_value": "AUCTION", "symbol": sym})
        add_event({"type": "SESSION_CHANGE", "action_value": "CONTINUOUS_TRADING", "symbol": sym})

    # Pattern 2 & 4: Sweepers, Corporate Actions, STP
    for i in range(2000):
        sym = symbols[i % len(symbols)]
        firm = random.choice(firms)
        
        # Random limit orders to keep book active
        side = random.choice(["BUY", "SELL"])
        price = random.randint(900, 1100)
        add_event({"type": "NEW_ORDER", "order_id": order_id, "firm_id": firm, "symbol": sym, "side": side, "order_type": "LIMIT", "price": price, "qty": random.randint(10, 100)})
        order_id += 1
        
        if i % 10 == 0:
            # Sweeper (Taker)
            add_event({"type": "NEW_ORDER", "order_id": order_id, "firm_id": firm, "symbol": sym, "side": side, "order_type": "LIMIT", "price": 2000 if side == "BUY" else 100, "qty": 500})
            order_id += 1
            
        if i % 15 == 0:
            # IOC
            add_event({"type": "NEW_ORDER", "order_id": order_id, "firm_id": firm, "symbol": sym, "side": side, "order_type": "IOC", "price": 2000 if side == "BUY" else 100, "qty": 200})
            order_id += 1
            
        if i % 20 == 0:
            # FOK
            add_event({"type": "NEW_ORDER", "order_id": order_id, "firm_id": firm, "symbol": sym, "side": side, "order_type": "FOK", "price": 2000 if side == "BUY" else 100, "qty": 50})
            order_id += 1
            
        if i % 100 == 0:
            # Split
            add_event({"type": "SPLIT", "action_value": 1.5, "symbol": sym})
            
        if i % 150 == 0:
            # Dividend
            add_event({"type": "DIVIDEND", "action_value": 50, "symbol": sym})
            
        if i % 75 == 0:
            # Modify to become taker
            target_id = random.randint(1, order_id - 1)
            add_event({"type": "MODIFY", "target_id": target_id, "price": 2000, "qty": 500, "symbol": sym})
            
        if i % 80 == 0:
            # Trade Bust
            target_id = random.randint(1, order_id - 1)
            add_event({"type": "BUST", "target_id": target_id, "symbol": sym})

    # MUTATION KILLERS
    sym = "SYM_MUT"
    firm1 = firms[0]
    firm2 = firms[1]
    firm3 = firms[2]
    
    add_event({"type": "SESSION_CHANGE", "action_value": "CONTINUOUS_TRADING", "symbol": sym})

    # Kill Iceberg priority loss
    # Firm1 puts Iceberg BUY at 500, total 100, visible 10
    add_event({"type": "NEW_ORDER", "order_id": order_id, "firm_id": firm1, "symbol": sym, "side": "BUY", "order_type": "ICEBERG", "price": 500, "qty": 100, "visible_qty": 10})
    ice_id = order_id
    order_id += 1
    # Firm2 puts Limit BUY at 500, qty 10
    add_event({"type": "NEW_ORDER", "order_id": order_id, "firm_id": firm2, "symbol": sym, "side": "BUY", "order_type": "LIMIT", "price": 500, "qty": 10})
    order_id += 1
    # Firm3 sells 10 at 500. Hits Iceberg. Iceberg refills, loses priority.
    add_event({"type": "NEW_ORDER", "order_id": order_id, "firm_id": firm3, "symbol": sym, "side": "SELL", "order_type": "LIMIT", "price": 500, "qty": 10})
    order_id += 1
    # Firm3 sells 10 at 500. Should hit Firm2 now.
    add_event({"type": "NEW_ORDER", "order_id": order_id, "firm_id": firm3, "symbol": sym, "side": "SELL", "order_type": "LIMIT", "price": 500, "qty": 10})
    order_id += 1
    
    # Kill Modify Maker into Taker
    # Firm1 puts Limit BUY at 400
    add_event({"type": "NEW_ORDER", "order_id": order_id, "firm_id": firm1, "symbol": sym, "side": "BUY", "order_type": "LIMIT", "price": 400, "qty": 10})
    mod_id = order_id
    order_id += 1
    # Firm2 puts Limit SELL at 410
    add_event({"type": "NEW_ORDER", "order_id": order_id, "firm_id": firm2, "symbol": sym, "side": "SELL", "order_type": "LIMIT", "price": 410, "qty": 10})
    order_id += 1
    # Firm1 modifies BUY to 410 (crosses spread, acts as taker, pays fees)
    add_event({"type": "MODIFY", "target_id": mod_id, "price": 410, "qty": 10, "symbol": sym})
    
    # Kill Dividend rounding/adjustment
    # Firm1 puts Limit BUY at 300
    add_event({"type": "NEW_ORDER", "order_id": order_id, "firm_id": firm1, "symbol": sym, "side": "BUY", "order_type": "LIMIT", "price": 300, "qty": 10})
    div_id = order_id
    order_id += 1
    # Dividend of 600
    add_event({"type": "DIVIDEND", "action_value": 600, "symbol": sym})
    # Firm2 sells at 0. Should match Firm1 (whose order is now 0).
    add_event({"type": "NEW_ORDER", "order_id": order_id, "firm_id": firm2, "symbol": sym, "side": "SELL", "order_type": "LIMIT", "price": 0, "qty": 10})
    order_id += 1

    with open(sys.argv[1], 'w') as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")

if __name__ == "__main__":
    main()
