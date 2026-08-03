import json
import sys
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class ExecutedTrade:
    trade_id: int
    maker_order_id: int
    taker_order_id: int
    buyer_firm: str
    seller_firm: str
    symbol: str
    price: int
    qty: int
    fiat_amount: int
    buyer_fee: int
    seller_fee: int
    busted: bool = False

@dataclass
class Order:
    order_id: int
    sequence_id: int
    priority_id: int
    firm_id: str
    symbol: str
    side: str
    order_type: str
    price: int
    qty: int
    visible_qty: int
    hidden_qty: int
    peg_offset: Optional[int]
    status: str = "OPEN" # OPEN, CANCELED, FILLED
    
    @property
    def is_buy(self):
        return self.side == "BUY"

class Ledger:
    def __init__(self):
        self.fiat: Dict[str, int] = defaultdict(int)
        self.positions: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.fees_paid: Dict[str, int] = defaultdict(int)
        self.trades: List[ExecutedTrade] = []
        self._next_trade_id = 1

    def execute_trade(self, maker_order: Order, taker_order: Order, price: int, qty: int, is_auction: bool):
        buyer = taker_order if taker_order.is_buy else maker_order
        seller = maker_order if taker_order.is_buy else taker_order
        
        buyer_fee = 0
        seller_fee = 0
        if not is_auction:
            if taker_order.is_buy:
                buyer_fee = 10 * qty
            else:
                seller_fee = 10 * qty

        fiat_amount = price * qty
        
        self.fiat[buyer.firm_id] -= fiat_amount
        self.fiat[seller.firm_id] += fiat_amount
        
        self.fiat[buyer.firm_id] -= buyer_fee
        self.fiat[seller.firm_id] -= seller_fee
        
        self.fees_paid[buyer.firm_id] += buyer_fee
        self.fees_paid[seller.firm_id] += seller_fee
        
        self.positions[buyer.firm_id][buyer.symbol] += qty
        self.positions[seller.firm_id][seller.symbol] -= qty

        trade = ExecutedTrade(
            trade_id=self._next_trade_id,
            maker_order_id=maker_order.order_id,
            taker_order_id=taker_order.order_id,
            buyer_firm=buyer.firm_id,
            seller_firm=seller.firm_id,
            symbol=buyer.symbol,
            price=price,
            qty=qty,
            fiat_amount=fiat_amount,
            buyer_fee=buyer_fee,
            seller_fee=seller_fee
        )
        self.trades.append(trade)
        self._next_trade_id += 1

    def apply_split(self, symbol: str, action_value: float):
        for firm, pos in self.positions.items():
            if pos[symbol] != 0:
                pos[symbol] = math.floor(pos[symbol] * action_value)
        
        for trade in self.trades:
            if trade.symbol == symbol and not trade.busted:
                trade.qty = math.floor(trade.qty * action_value)

    def bust_trades(self, order_id: int):
        for trade in self.trades:
            if not trade.busted and (trade.maker_order_id == order_id or trade.taker_order_id == order_id):
                trade.busted = True
                self.fiat[trade.buyer_firm] += trade.fiat_amount
                self.fiat[trade.seller_firm] -= trade.fiat_amount
                
                # Fees are not refunded
                
                self.positions[trade.buyer_firm][trade.symbol] -= trade.qty
                self.positions[trade.seller_firm][trade.symbol] += trade.qty

    def to_json(self):
        res = {}
        for firm in sorted(self.fiat.keys() | self.fees_paid.keys() | self.positions.keys()):
            pos = {sym: q for sym, q in self.positions.get(firm, {}).items() if q != 0}
            res[firm] = {
                "fiat": self.fiat.get(firm, 0),
                "positions": pos,
                "fees_paid": self.fees_paid.get(firm, 0)
            }
        return res

class OrderBook:
    def __init__(self, symbol: str, engine):
        self.symbol = symbol
        self.engine = engine
        self.orders: Dict[int, Order] = {}
        self.bids: List[int] = [] 
        self.asks: List[int] = []
        self.session_state = "PRE_MARKET"
        self.last_continuous_trade_price: int = 0
        
    def best_bid(self) -> Optional[int]:
        valid_bids = [self.orders[oid] for oid in self.bids if self.orders[oid].status == "OPEN" and self.orders[oid].order_type != "PEGGED"]
        if not valid_bids: return None
        return max(valid_bids, key=lambda o: o.price).price

    def best_ask(self) -> Optional[int]:
        valid_asks = [self.orders[oid] for oid in self.asks if self.orders[oid].status == "OPEN" and self.orders[oid].order_type != "PEGGED"]
        if not valid_asks: return None
        return min(valid_asks, key=lambda o: o.price).price

    def recalculate_pegged_orders(self, trigger_sequence_id: int):
        if self.session_state == "AUCTION":
            return
            
        bbo_bid = self.best_bid()
        bbo_ask = self.best_ask()

        pegged_orders = [self.orders[oid] for oid in list(self.orders.keys()) if self.orders[oid].status == "OPEN" and self.orders[oid].order_type == "PEGGED"]
        
        updated_pegged = []
        for p_order in pegged_orders:
            if p_order.is_buy:
                if bbo_bid is None:
                    p_order.status = "CANCELED"
                else:
                    new_price = bbo_bid + p_order.peg_offset
                    if new_price != p_order.price:
                        p_order.price = new_price
                        updated_pegged.append(p_order)
            else:
                if bbo_ask is None:
                    p_order.status = "CANCELED"
                else:
                    new_price = bbo_ask + p_order.peg_offset
                    if new_price != p_order.price:
                        p_order.price = new_price
                        updated_pegged.append(p_order)
                        
        updated_pegged.sort(key=lambda o: o.order_id)
        for p_order in updated_pegged:
            p_order.priority_id = trigger_sequence_id

    def handle_dividend(self, amount: int, sequence_id: int):
        updated = False
        for oid, order in self.orders.items():
            if order.status == "OPEN" and order.is_buy and order.order_type in ("LIMIT", "ICEBERG"):
                order.price = max(0, order.price - amount)
                updated = True
        if updated:
            self.recalculate_pegged_orders(sequence_id)

    def handle_split(self, action_value: float, sequence_id: int):
        updated = False
        for oid, order in self.orders.items():
            if order.status == "OPEN":
                order.qty = math.floor(order.qty * action_value)
                order.visible_qty = math.floor(order.visible_qty * action_value)
                order.hidden_qty = math.floor(order.hidden_qty * action_value)
                if order.order_type in ("LIMIT", "ICEBERG"):
                    if order.is_buy:
                        order.price = math.floor(order.price / action_value)
                    else:
                        order.price = math.ceil(order.price / action_value)
                    updated = True
        
        self.engine.ledger.apply_split(self.symbol, action_value)
        if updated:
            self.recalculate_pegged_orders(sequence_id)

    def remove_dead_orders(self):
        self.bids = [oid for oid in self.bids if self.orders[oid].status == "OPEN"]
        self.asks = [oid for oid in self.asks if self.orders[oid].status == "OPEN"]

    def add_order(self, order: Order):
        if self.session_state in ("PRE_MARKET", "HALTED", "AUCTION") and order.order_type == "MARKET":
            order.status = "REJECTED"
            return
            
        if order.order_type == "PEGGED":
            bbo = self.best_bid() if order.is_buy else self.best_ask()
            if bbo is None:
                order.status = "CANCELED"
                return
            order.price = bbo + order.peg_offset
            
        self.orders[order.order_id] = order
        if order.is_buy:
            self.bids.append(order.order_id)
        else:
            self.asks.append(order.order_id)
            
        if self.session_state == "CONTINUOUS_TRADING":
            self.match_continuous(order)

    def cancel_order(self, order_id: int):
        if order_id in self.orders and self.orders[order_id].status == "OPEN":
            self.orders[order_id].status = "CANCELED"
            self.recalculate_pegged_orders(self.engine.current_sequence_id)

    def modify_order(self, order_id: int, new_qty: int, new_price: int, sequence_id: int):
        if order_id not in self.orders or self.orders[order_id].status != "OPEN":
            return
        order = self.orders[order_id]
        filled_qty = (order.qty - order.visible_qty - order.hidden_qty) if order.order_type == "ICEBERG" else (order.qty - order.visible_qty)
        
        new_remaining = new_qty - filled_qty
        if new_remaining <= 0:
            order.status = "CANCELED"
        else:
            if new_qty > order.qty or new_price != order.price:
                # Cancel and Replace
                if order.is_buy:
                    if order.order_id in self.bids: self.bids.remove(order.order_id)
                else:
                    if order.order_id in self.asks: self.asks.remove(order.order_id)
                order.status = "CANCELED"
                new_order = Order(
                    order_id=order.order_id,
                    sequence_id=sequence_id,
                    priority_id=sequence_id,
                    firm_id=order.firm_id,
                    symbol=order.symbol,
                    side=order.side,
                    order_type=order.order_type,
                    price=new_price,
                    qty=new_qty,
                    visible_qty=new_remaining if order.order_type != "ICEBERG" else min(new_remaining, order._refill_qty),
                    hidden_qty=0 if order.order_type != "ICEBERG" else max(0, new_remaining - order._refill_qty),
                    peg_offset=order.peg_offset
                )
                if new_order.order_type == "ICEBERG":
                    new_order._refill_qty = order._refill_qty
                    def refill(new_p_id, o=new_order):
                        if o.hidden_qty > 0:
                            r = min(o.hidden_qty, o._refill_qty)
                            o.visible_qty += r
                            o.hidden_qty -= r
                            o.priority_id = new_p_id
                    new_order.refill = refill
                self.add_order(new_order)
            else:
                # Keep priority
                order.qty = new_qty
                if order.order_type == "ICEBERG":
                    diff = order.visible_qty + order.hidden_qty - new_remaining
                    if diff <= order.hidden_qty:
                        order.hidden_qty -= diff
                    else:
                        order.visible_qty -= (diff - order.hidden_qty)
                        order.hidden_qty = 0
                else:
                    order.visible_qty = new_remaining
        
        self.recalculate_pegged_orders(sequence_id)

    def get_sorted_book(self, is_buy: bool):
        self.remove_dead_orders()
        oids = self.bids if is_buy else self.asks
        orders = [self.orders[oid] for oid in oids]
        if is_buy:
            orders.sort(key=lambda o: (-o.price, o.priority_id, o.order_id))
        else:
            orders.sort(key=lambda o: (o.price, o.priority_id, o.order_id))
        return orders

    def match_continuous(self, taker: Order):
        if taker.order_type == "FOK":
            needed = taker.visible_qty
            resting = self.get_sorted_book(not taker.is_buy)
            can_fill = True
            for maker in resting:
                if taker.order_type != "MARKET" and ((taker.is_buy and maker.price > taker.price) or (not taker.is_buy and maker.price < taker.price)):
                    break
                if maker.firm_id == taker.firm_id:
                    can_fill = False
                    break
                needed -= (maker.visible_qty + maker.hidden_qty)
                if needed <= 0:
                    break
            if needed > 0 or not can_fill:
                taker.status = "CANCELED"
                return

        while taker.status == "OPEN" and taker.visible_qty > 0:
            resting = self.get_sorted_book(not taker.is_buy)
            if not resting:
                break
                
            maker = resting[0]
            if taker.order_type != "MARKET":
                if taker.is_buy and maker.price > taker.price:
                    break
                if not taker.is_buy and maker.price < taker.price:
                    break
                    
            if taker.firm_id == maker.firm_id:
                taker.status = "CANCELED"
                break
                
            match_qty = min(taker.visible_qty, maker.visible_qty)
            match_price = maker.price
            
            taker.visible_qty -= match_qty
            maker.visible_qty -= match_qty
            
            self.engine.ledger.execute_trade(maker, taker, match_price, match_qty, False)
            self.last_continuous_trade_price = match_price
            
            if maker.visible_qty == 0:
                if maker.order_type == "ICEBERG" and maker.hidden_qty > 0:
                    maker.refill(self.engine.current_sequence_id)
                else:
                    maker.status = "FILLED"
                    
            if taker.visible_qty == 0:
                taker.status = "FILLED"

            self.recalculate_pegged_orders(self.engine.current_sequence_id)

        if taker.status == "OPEN":
            if taker.order_type in ("IOC", "FOK", "MARKET"):
                taker.status = "CANCELED"

    def process_auction(self, sequence_id: int):
        self.remove_dead_orders()
        bids = [self.orders[oid] for oid in self.bids if self.orders[oid].status == "OPEN" and self.orders[oid].order_type != "MARKET"]
        asks = [self.orders[oid] for oid in self.asks if self.orders[oid].status == "OPEN" and self.orders[oid].order_type != "MARKET"]
        
        prices = set([o.price for o in bids + asks])
        best_price = None
        max_vol = -1
        min_imb = float('inf')
        
        for p in prices:
            exec_buy = sum(o.visible_qty + o.hidden_qty for o in bids if o.price >= p)
            exec_sell = sum(o.visible_qty + o.hidden_qty for o in asks if o.price <= p)
            vol = min(exec_buy, exec_sell)
            imb = abs(exec_buy - exec_sell)
            
            if vol > max_vol:
                max_vol = vol
                min_imb = imb
                best_price = p
            elif vol == max_vol:
                if imb < min_imb:
                    min_imb = imb
                    best_price = p
                elif imb == min_imb:
                    dist1 = abs(p - self.last_continuous_trade_price)
                    dist2 = abs(best_price - self.last_continuous_trade_price) if best_price is not None else float('inf')
                    if dist1 < dist2:
                        best_price = p
                    elif dist1 == dist2:
                        if p > best_price:
                            best_price = p
                            
        if max_vol == 0 or best_price is None:
            return

        exec_bids = [o for o in bids if o.price >= best_price]
        exec_asks = [o for o in asks if o.price <= best_price]
        
        exec_bids.sort(key=lambda o: (-o.price, o.priority_id, o.order_id))
        exec_asks.sort(key=lambda o: (o.price, o.priority_id, o.order_id))
        
        while exec_bids and exec_asks and max_vol > 0:
            b = exec_bids[0]
            a = exec_asks[0]
            match_qty = min(b.visible_qty + b.hidden_qty, a.visible_qty + a.hidden_qty, max_vol)
            
            max_vol -= match_qty
            
            self.engine.ledger.execute_trade(a, b, best_price, match_qty, True)
            
            def reduce_order(o, q):
                if o.order_type == "ICEBERG":
                    diff = o.visible_qty + o.hidden_qty - (o.visible_qty + o.hidden_qty - q)
                    if diff <= o.hidden_qty:
                        o.hidden_qty -= diff
                    else:
                        o.visible_qty -= (diff - o.hidden_qty)
                        o.hidden_qty = 0
                else:
                    o.visible_qty -= q
                if o.visible_qty + o.hidden_qty == 0:
                    o.status = "FILLED"
                    
            reduce_order(b, match_qty)
            reduce_order(a, match_qty)
            
            if b.status == "FILLED":
                exec_bids.pop(0)
            if a.status == "FILLED":
                exec_asks.pop(0)

class Engine:
    def __init__(self):
        self.books: Dict[str, OrderBook] = {}
        self.ledger = Ledger()
        self.current_sequence_id = 0
        self._internal_id_counter = 1000000

    def get_next_internal_id(self):
        self._internal_id_counter += 1
        return self._internal_id_counter

    def get_book(self, symbol: str) -> OrderBook:
        if symbol not in self.books:
            self.books[symbol] = OrderBook(symbol, self)
        return self.books[symbol]

    def process_event(self, ev: dict):
        self.current_sequence_id = ev['sequence_id']
        etype = ev['type']
        sym = ev.get('symbol')
        book = self.get_book(sym) if sym else None
        
        if etype == "NEW_ORDER":
            o = Order(
                order_id=ev['order_id'],
                sequence_id=self.current_sequence_id,
                priority_id=self.current_sequence_id,
                firm_id=ev['firm_id'],
                symbol=sym,
                side=ev['side'],
                order_type=ev['order_type'],
                price=ev.get('price', 0),
                qty=ev['qty'],
                visible_qty=ev.get('visible_qty', ev['qty']),
                hidden_qty=ev['qty'] - ev.get('visible_qty', ev['qty']),
                peg_offset=ev.get('peg_offset')
            )
            if o.order_type == "ICEBERG":
                o._refill_qty = o.visible_qty
                def refill(new_p_id, o=o):
                    if o.hidden_qty > 0:
                        r = min(o.hidden_qty, o._refill_qty)
                        o.visible_qty += r
                        o.hidden_qty -= r
                        o.priority_id = new_p_id
                o.refill = refill
                
            book.add_order(o)
        
        elif etype == "CANCEL":
            book.cancel_order(ev['target_id'])
            
        elif etype == "MODIFY":
            book.modify_order(ev['target_id'], ev['qty'], ev['price'], self.current_sequence_id)
            
        elif etype == "DIVIDEND":
            book.handle_dividend(ev['action_value'], self.current_sequence_id)
            
        elif etype == "SPLIT":
            book.handle_split(ev['action_value'], self.current_sequence_id)
            
        elif etype == "BUST":
            self.ledger.bust_trades(ev['target_id'])
            
        elif etype == "SESSION_CHANGE":
            new_session = ev['action_value']
            if new_session == "AUCTION" and book.session_state != "AUCTION":
                book.session_state = "AUCTION"
                book.process_auction(self.current_sequence_id)
            book.session_state = new_session
            
def main():
    if len(sys.argv) != 3:
        sys.exit(1)
        
    engine = Engine()
    
    with open(sys.argv[1], 'r') as f:
        for line in f:
            if not line.strip(): continue
            ev = json.loads(line)
            engine.process_event(ev)
            
    with open(sys.argv[2], 'w') as f:
        json.dump(engine.ledger.to_json(), f, indent=2)

if __name__ == "__main__":
    main()
