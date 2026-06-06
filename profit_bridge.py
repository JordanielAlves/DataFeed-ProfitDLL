"""
profit_bridge.py
Wrapper da ProfitDLL para leitura de fluxo de ordens.
Gerencia inicialização, callbacks e subscriptions.
"""

import struct
import threading
from ctypes import *
from datetime import datetime
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Estruturas de dados (espelho do profitTypes.py do exemplo oficial)
# ---------------------------------------------------------------------------

class TAssetID(Structure):
    _fields_ = [
        ("ticker", c_wchar_p),
        ("bolsa",  c_wchar_p),
        ("feed",   c_int),
    ]

class TConnectorAssetIdentifier(Structure):
    _fields_ = [
        ("Version",  c_ubyte),
        ("Ticker",   c_wchar_p),
        ("Exchange", c_wchar_p),
        ("FeedType", c_ubyte),
    ]

class SystemTime(Structure):
    _fields_ = [
        ("wYear",         c_ushort),
        ("wMonth",        c_ushort),
        ("wDayOfWeek",    c_ushort),
        ("wDay",          c_ushort),
        ("wHour",         c_ushort),
        ("wMinute",       c_ushort),
        ("wSecond",       c_ushort),
        ("wMilliseconds", c_ushort),
    ]

class TConnectorTrade(Structure):
    _fields_ = [
        ("Version",     c_ubyte),
        ("TradeDate",   SystemTime),
        ("TradeNumber", c_uint),
        ("Price",       c_double),
        ("Quantity",    c_longlong),   # Int64 — NUNCA usar c_long no Windows x64
        ("Volume",      c_double),
        ("BuyAgent",    c_int),
        ("SellAgent",   c_int),
        ("TradeType",   c_ubyte),
    ]

class TConnectorPriceGroup(Structure):
    """
    Estrutura retornada por GetPriceGroup.
    Representa um nível de preço no livro de profundidade (price depth).
    ATENÇÃO: Quantity é Int64. Usar c_longlong, nunca c_long.
    """
    _fields_ = [
        ("Version",         c_ubyte),
        ("Price",           c_double),
        ("Count",           c_uint),       # número de ofertas individuais naquele preço
        ("Quantity",        c_longlong),   # quantidade total ofertada — Int64!
        ("PriceGroupFlags", c_uint),       # PG_IS_THEORIC = 1 (preço teórico em leilão)
    ]

# Flag de price group
PG_IS_THEORIC = 1

# ---------------------------------------------------------------------------
# Constantes de TradeType — conforme documentação oficial Nelogica
# ---------------------------------------------------------------------------
TRADE_TYPE_CROSS       = 1   # cross trade (direto dentro da corretora)
TRADE_TYPE_BUY         = 2   # comprador agrediu (lift da ask)
TRADE_TYPE_SELL        = 3   # vendedor agrediu (hit da bid)
TRADE_TYPE_LEILAO      = 4   # leilão
TRADE_TYPE_SURVEILLANCE= 5
TRADE_TYPE_EXPIT       = 6
TRADE_TYPE_OPCAO       = 7
TRADE_TYPE_OTC         = 8
TRADE_TYPE_DESCONHECIDO= 32

# ---------------------------------------------------------------------------
# Constantes de estado de conexão — TConnectorStateType + resultados
# ---------------------------------------------------------------------------
# state_type values (nType no callback):
STATE_TYPE_LOGIN      = 0   # login no servidor
STATE_TYPE_ROUTING    = 1   # conexão de roteamento de ordens
STATE_TYPE_MARKET     = 2   # conexão de market data
STATE_TYPE_ACTIVATION = 3   # validação de licença/ativação

# Resultados de login (state_type=0):
LOGIN_OK              = 0
LOGIN_ALREADY         = 1
LOGIN_INVALID_KEY     = 2
LOGIN_CONN_FAILED     = 3

# Resultados de market data (state_type=2) — mercado pronto = 4:
MARKET_DISCONNECTED   = 0
MARKET_CONNECTING     = 1
MARKET_CONNECTED      = 2
MARKET_RECONECTING    = 3
MARKET_DATA_READY     = 4   # ← estado que indica mercado pronto para receber dados

# Resultados de ativação (state_type=3):
ACTIVATION_OK         = 0   # ativação válida — pronto para operar
ACTIVATION_INVALID    = 1
ACTIVATION_EXPIRED    = 2

# ---------------------------------------------------------------------------
# Constantes do Price Depth (livro de profundidade agregado)
# ---------------------------------------------------------------------------
# TConnectorBookSideType:
BOOK_SIDE_BUY  = 0   # bsBuy  — lado da compra (bid)
BOOK_SIDE_SELL = 1   # bsSell — lado da venda (ask)
BOOK_SIDE_BOTH = 254
BOOK_SIDE_NONE = 255

# TConnectorUpdateType (tipo de atualização no callback de price depth):
PD_UPDATE_ADD         = 0   # utAdd        — novo nível adicionado
PD_UPDATE_EDIT        = 1   # utEdit       — nível modificado
PD_UPDATE_DELETE      = 2   # utDelete     — nível removido
PD_UPDATE_INSERT      = 3   # utInsert     — nível inserido em posição específica
PD_UPDATE_FULL_BOOK   = 4   # utFullBook   — livro completo re-entregue
PD_UPDATE_PREPARE     = 5   # utPrepare    — início de rajada de atualizações
PD_UPDATE_FLUSH       = 6   # utFlush      — fim de rajada (processar aqui)
PD_UPDATE_THEORIC     = 7   # utTheoricPrice — preço teórico mudou (leilão)
PD_UPDATE_DELETE_FROM = 8   # utDeleteFrom — remoção em lote a partir de posição

def is_buy_aggression(trade_type: int) -> bool:
    return trade_type == TRADE_TYPE_BUY

def is_sell_aggression(trade_type: int) -> bool:
    return trade_type == TRADE_TYPE_SELL

def is_cross(trade_type: int) -> bool:
    return trade_type == TRADE_TYPE_CROSS

def is_relevant(trade_type: int) -> bool:
    """Retorna True apenas para trades de fluxo real (ignora leilão, OTC, etc.)"""
    return trade_type in (TRADE_TYPE_BUY, TRADE_TYPE_SELL, TRADE_TYPE_CROSS)

# ---------------------------------------------------------------------------
# Evento de trade normalizado
# ---------------------------------------------------------------------------
class TradeEvent:
    __slots__ = ("ticker", "price", "qty", "volume",
                 "buy_agent", "sell_agent", "trade_type",
                 "ts", "trade_number")

    def __init__(self, ticker, price, qty, volume,
                 buy_agent, sell_agent, trade_type, ts, trade_number):
        self.ticker       = ticker
        self.price        = price
        self.qty          = qty
        self.volume       = volume
        self.buy_agent    = buy_agent
        self.sell_agent   = sell_agent
        self.trade_type   = trade_type   # 1=buy agg, 2=sell agg, 0=cross
        self.ts           = ts           # datetime
        self.trade_number = trade_number

    @property
    def is_buy_aggression(self) -> bool:
        return self.trade_type == TRADE_TYPE_BUY   # type 2

    @property
    def is_sell_aggression(self) -> bool:
        return self.trade_type == TRADE_TYPE_SELL  # type 3

    @property
    def is_relevant(self) -> bool:
        """Filtra leilão, OTC e tipos especiais — mantém só fluxo real."""
        return is_relevant(self.trade_type)

    def __repr__(self):
        side = "BUY " if self.is_buy_aggression else ("SELL" if self.is_sell_aggression else "CRSS")
        return (f"[{self.ts.strftime('%H:%M:%S.%f')[:-3]}] "
                f"{self.ticker} {side} "
                f"P={self.price:.2f} Q={self.qty} V={self.volume:.0f}")


# ---------------------------------------------------------------------------
# Evento de book (oferta individual)
# ---------------------------------------------------------------------------
class BookEvent:
    ACTION_ADD        = 0
    ACTION_EDIT       = 1
    ACTION_DELETE     = 2
    ACTION_DELETE_FROM= 3
    ACTION_FULL_BOOK  = 4

    SIDE_BUY  = 0
    SIDE_SELL = 1

    __slots__ = ("ticker", "action", "position", "side",
                 "qty", "agent", "offer_id", "price", "ts")

    def __init__(self, ticker, action, position, side,
                 qty, agent, offer_id, price, ts):
        self.ticker   = ticker
        self.action   = action
        self.position = position
        self.side     = side
        self.qty      = qty
        self.agent    = agent
        self.offer_id = offer_id
        self.price    = price
        self.ts       = ts


# ---------------------------------------------------------------------------
# Evento de Price Depth (notificação de mudança no livro agregado)
# ---------------------------------------------------------------------------
class PriceDepthEvent:
    """
    Disparado quando há mudança no livro de profundidade (price depth).
    Não contém os dados do nível — apenas sinaliza que houve mudança.
    Para ler o livro atual, chame ProfitBridge.get_price_depth(ticker, exchange).

    update_type: PD_UPDATE_* constants
    side:        BOOK_SIDE_BUY ou BOOK_SIDE_SELL
    position:    índice do nível afetado (0 = topo do livro)
    """
    __slots__ = ("ticker", "side", "position", "update_type")

    def __init__(self, ticker: str, side: int, position: int, update_type: int):
        self.ticker      = ticker
        self.side        = side
        self.position    = position
        self.update_type = update_type

    @property
    def is_flush(self) -> bool:
        """True quando é fim de rajada — momento ideal para processar o livro."""
        return self.update_type == PD_UPDATE_FLUSH

    @property
    def is_full_book(self) -> bool:
        return self.update_type == PD_UPDATE_FULL_BOOK


# ---------------------------------------------------------------------------
# Evento de daily (saldo acumulado do dia)
# ---------------------------------------------------------------------------
class DailyEvent:
    __slots__ = ("ticker", "date", "open_", "high", "low", "close",
                 "vol", "qty_buyer", "qty_seller",
                 "neg_buyer", "neg_seller", "vol_buyer", "vol_seller",
                 "contracts_open")

    def __init__(self, ticker, date, open_, high, low, close, vol,
                 qty_buyer, qty_seller, neg_buyer, neg_seller,
                 vol_buyer, vol_seller, contracts_open):
        self.ticker         = ticker
        self.date           = date
        self.open_          = open_
        self.high           = high
        self.low            = low
        self.close          = close
        self.vol            = vol
        self.qty_buyer      = qty_buyer
        self.qty_seller     = qty_seller
        self.neg_buyer      = neg_buyer
        self.neg_seller     = neg_seller
        self.vol_buyer      = vol_buyer
        self.vol_seller     = vol_seller
        self.contracts_open = contracts_open

    @property
    def daily_delta(self) -> int:
        """Delta acumulado do dia fornecido diretamente pela DLL."""
        return self.qty_buyer - self.qty_seller


# ---------------------------------------------------------------------------
# Bridge principal
# ---------------------------------------------------------------------------
class ProfitBridge:
    """
    Encapsula a ProfitDLL e expõe callbacks tipados para:
      - on_trade(TradeEvent)
      - on_book(BookEvent)
      - on_daily(DailyEvent)
      - on_connected(bool)
    """

    def __init__(self, dll_path: str):
        self._dll = WinDLL(dll_path)
        self._setup_restype()

        # Callbacks externos (registrados pelo usuário desta classe)
        self.on_trade:       Optional[Callable[[TradeEvent],       None]] = None
        self.on_book:        Optional[Callable[[BookEvent],        None]] = None
        self.on_daily:       Optional[Callable[[DailyEvent],       None]] = None
        self.on_connected:   Optional[Callable[[bool],             None]] = None
        self.on_price_depth: Optional[Callable[[PriceDepthEvent],  None]] = None

        # Estado de conexão
        self._market_connected = False
        self._activated        = False
        self._logged_in        = False
        self._lock             = threading.Lock()

        # Manter referências dos callbacks para evitar GC
        self._cb_state      = None
        self._cb_trade      = None
        self._cb_book       = None
        self._cb_daily      = None
        self._cb_progress   = None
        self._cb_tiny       = None
        self._cb_price_book = None
        self._cb_price_depth= None   # price depth (agregado por nível)

    # ------------------------------------------------------------------
    # Setup de retornos da DLL
    # ------------------------------------------------------------------
    def _setup_restype(self):
        dll = self._dll
        dll.TranslateTrade.argtypes  = [c_size_t, POINTER(TConnectorTrade)]
        dll.TranslateTrade.restype   = c_int
        dll.SubscribeTicker.restype  = c_int
        dll.SubscribeOfferBook.restype = c_int
        dll.DLLFinalize.restype      = c_int
        # Price Depth
        dll.SubscribePriceDepth.restype        = c_int
        dll.UnsubscribePriceDepth.restype      = c_int
        dll.GetPriceDepthSideCount.restype     = c_int
        dll.GetPriceGroup.restype              = c_int
        dll.GetTheoreticalValues.restype       = c_int

    # ------------------------------------------------------------------
    # Inicialização / login
    # ------------------------------------------------------------------
    def initialize(self, access_key: str, user: str, password: str,
                   market_only: bool = False) -> int:
        """
        Inicializa a DLL e conecta ao servidor Nelogica.
        market_only=True: sem roteamento (apenas market data).
        """
        self._cb_state      = self._make_state_callback()
        self._cb_trade      = self._make_trade_callback()
        self._cb_book       = self._make_book_callback()
        self._cb_daily      = self._make_daily_callback()
        self._cb_progress   = self._make_progress_callback()
        self._cb_tiny       = self._make_tiny_callback()
        self._cb_price_book = self._make_price_book_callback()

        if market_only:
            result = self._dll.DLLInitializeMarketLogin(
                c_wchar_p(access_key),
                c_wchar_p(user),
                c_wchar_p(password),
                self._cb_state,
                None,                    # history trade
                self._cb_daily,
                self._cb_price_book,
                None,                    # change cotation
                None,                    # change state ticker
                self._cb_progress,
                self._cb_tiny,
            )
        else:
            result = self._dll.DLLInitializeLogin(
                c_wchar_p(access_key),
                c_wchar_p(user),
                c_wchar_p(password),
                self._cb_state,
                None,                    # order change
                None,                    # history
                None,                    # account
                None,                    # new trade (legacy)
                self._cb_daily,
                self._cb_price_book,
                None,                    # change cotation
                None,                    # change state ticker
                self._cb_progress,
                self._cb_tiny,
            )

        # Registrar callbacks adicionais
        self._dll.SetOfferBookCallbackV2(self._cb_book)
        self._dll.SetTradeCallbackV2(self._cb_trade)

        return result

    def finalize(self):
        self._dll.DLLFinalize()

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------
    def subscribe(self, ticker: str, exchange: str = "F"):
        """Inscreve em trades (ticker) e book de ofertas."""
        self._dll.SubscribeTicker(c_wchar_p(ticker), c_wchar_p(exchange))
        self._dll.SubscribeOfferBook(c_wchar_p(ticker), c_wchar_p(exchange))

    def unsubscribe(self, ticker: str, exchange: str = "F"):
        self._dll.UnsubscribeTicker(c_wchar_p(ticker), c_wchar_p(exchange))

    # ------------------------------------------------------------------
    # Estado de conexão
    # ------------------------------------------------------------------
    @property
    def is_connected(self) -> bool:
        return self._market_connected and self._activated

    def wait_connected(self, timeout: float = 30.0) -> bool:
        """Bloqueia até conectar ou timeout (segundos)."""
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_connected:
                return True
            time.sleep(0.1)
        return False

    # ------------------------------------------------------------------
    # Fabricação dos callbacks C (WINFUNCTYPE)
    # ------------------------------------------------------------------
    def _make_state_callback(self):
        bridge = self

        @WINFUNCTYPE(None, c_int32, c_int32)
        def _cb(nType, nResult):
            with bridge._lock:
                if nType == STATE_TYPE_LOGIN:
                    bridge._logged_in = (nResult == LOGIN_OK)
                elif nType == STATE_TYPE_MARKET:
                    bridge._market_connected = (nResult == MARKET_DATA_READY)
                elif nType == STATE_TYPE_ACTIVATION:
                    bridge._activated = (nResult == ACTIVATION_OK)

            if bridge.on_connected:
                bridge.on_connected(bridge.is_connected)

        return _cb

    def _make_trade_callback(self):
        bridge = self
        dll    = self._dll

        @WINFUNCTYPE(None, TConnectorAssetIdentifier, c_size_t, c_uint)
        def _cb(assetId, pTrade, flags):
            trade_struct = TConnectorTrade(Version=0)
            if not dll.TranslateTrade(pTrade, byref(trade_struct)):
                return

            st  = trade_struct.TradeDate
            try:
                ts = datetime(st.wYear, st.wMonth, st.wDay,
                              st.wHour, st.wMinute, st.wSecond,
                              st.wMilliseconds * 1000)
            except Exception:
                ts = datetime.now()

            event = TradeEvent(
                ticker       = assetId.Ticker or "",
                price        = trade_struct.Price,
                qty          = int(trade_struct.Quantity),
                volume       = trade_struct.Volume,
                buy_agent    = trade_struct.BuyAgent,
                sell_agent   = trade_struct.SellAgent,
                trade_type   = int(trade_struct.TradeType),
                ts           = ts,
                trade_number = trade_struct.TradeNumber,
            )

            if bridge.on_trade:
                bridge.on_trade(event)

        return _cb

    def _make_book_callback(self):
        bridge = self

        @WINFUNCTYPE(None,
                     TAssetID, c_int, c_int, c_int, c_int, c_int,
                     c_longlong, c_double,
                     c_int, c_int, c_int, c_int, c_int,
                     c_wchar_p, POINTER(c_ubyte), POINTER(c_ubyte))
        def _cb(assetId, nAction, nPosition, side, nQtd, nAgent,
                nOfferID, sPrice,
                bHasPrice, bHasQtd, bHasDate, bHasOfferID, bHasAgent,
                date, pArraySell, pArrayBuy):

            event = BookEvent(
                ticker   = assetId.ticker or "",
                action   = nAction,
                position = nPosition,
                side     = side,
                qty      = nQtd,
                agent    = nAgent,
                offer_id = nOfferID,
                price    = sPrice,
                ts       = datetime.now(),
            )

            if bridge.on_book:
                bridge.on_book(event)

        return _cb

    def _make_daily_callback(self):
        bridge = self

        @WINFUNCTYPE(None,
                     TAssetID, c_wchar_p,
                     c_double, c_double, c_double, c_double,
                     c_double, c_double, c_double, c_double,
                     c_double, c_double,
                     c_int, c_int, c_int, c_int, c_int, c_int, c_int)
        def _cb(assetId, date,
                sOpen, sHigh, sLow, sClose, sVol, sAjuste,
                sMaxLimit, sMinLimit,
                sVolBuyer, sVolSeller,
                nQtd, nNegocios, nContratosOpen,
                nQtdBuyer, nQtdSeller, nNegBuyer, nNegSeller):

            event = DailyEvent(
                ticker         = assetId.ticker or "",
                date           = date or "",
                open_          = sOpen,
                high           = sHigh,
                low            = sLow,
                close          = sClose,
                vol            = sVol,
                qty_buyer      = nQtdBuyer,
                qty_seller     = nQtdSeller,
                neg_buyer      = nNegBuyer,
                neg_seller     = nNegSeller,
                vol_buyer      = sVolBuyer,
                vol_seller     = sVolSeller,
                contracts_open = nContratosOpen,
            )

            if bridge.on_daily:
                bridge.on_daily(event)

        return _cb

    # ------------------------------------------------------------------
    # Price Depth (livro agregado por nível de preço)
    # ------------------------------------------------------------------

    def setup_price_depth(self):
        """
        Registra o callback de price depth.
        Chamar UMA VEZ após initialize(), antes de subscribe_price_depth().
        Requer que on_price_depth esteja definido no objeto.
        """
        self._cb_price_depth = self._make_price_depth_callback()
        self._dll.SetPriceDepthCallback(self._cb_price_depth)

    def subscribe_price_depth(self, ticker: str, exchange: str = "F") -> bool:
        """
        Assina o livro de profundidade de um ativo.
        Retorna True se sucesso (código NL_OK = 0).
        """
        asset = TConnectorAssetIdentifier()
        asset.Version  = 0
        asset.Ticker   = ticker
        asset.Exchange = exchange
        asset.FeedType = 0
        ret = self._dll.SubscribePriceDepth(byref(asset))
        return ret == 0

    def unsubscribe_price_depth(self, ticker: str, exchange: str = "F"):
        asset = TConnectorAssetIdentifier()
        asset.Version  = 0
        asset.Ticker   = ticker
        asset.Exchange = exchange
        asset.FeedType = 0
        self._dll.UnsubscribePriceDepth(byref(asset))

    def get_price_depth(self, ticker: str, exchange: str = "F",
                        n_levels: int = 20) -> dict:
        """
        Lê o estado atual do livro de profundidade (price depth).
        Retorna dict com chaves 'bid' e 'ask', cada uma lista de dicts:
            [{"price": float, "qty": int, "count": int, "is_theoric": bool}, ...]

        Chamar de uma thread separada (NÃO dentro do callback — bloqueia ConnectorThread).
        A posição 0 é sempre o topo (melhor bid / melhor ask).
        """
        asset = TConnectorAssetIdentifier()
        asset.Version  = 0
        asset.Ticker   = ticker
        asset.Exchange = exchange
        asset.FeedType = 0

        result = {"bid": [], "ask": []}

        for side_name, side_int in [("bid", BOOK_SIDE_BUY), ("ask", BOOK_SIDE_SELL)]:
            total = self._dll.GetPriceDepthSideCount(byref(asset), side_int)
            for pos in range(min(n_levels, total)):
                grupo = TConnectorPriceGroup()
                grupo.Version = 0
                ret = self._dll.GetPriceGroup(byref(asset), side_int, pos, byref(grupo))
                if ret == 0:
                    is_theoric = bool(grupo.PriceGroupFlags & PG_IS_THEORIC)
                    result[side_name].append({
                        "price":      grupo.Price if not is_theoric else None,
                        "qty":        grupo.Quantity,
                        "count":      grupo.Count,
                        "is_theoric": is_theoric,
                    })

        return result

    def _make_price_depth_callback(self):
        bridge = self

        # ATENÇÃO à assinatura exata — erros aqui travam o processo silenciosamente:
        #   - asset por VALOR (não ponteiro)
        #   - side e updateType são c_ubyte, NÃO c_int
        @WINFUNCTYPE(
            None,
            TConnectorAssetIdentifier,  # asset (por valor)
            c_ubyte,                    # side (0=bid, 1=ask)
            c_int,                      # position (índice do nível; 0=topo)
            c_ubyte,                    # updateType (PD_UPDATE_*)
        )
        def _cb(asset, side, position, update_type):
            # NÃO chamar GetPriceGroup aqui — bloqueia ConnectorThread
            # Apenas enfileirar/notificar; processar em thread separada
            if bridge.on_price_depth:
                event = PriceDepthEvent(
                    ticker      = asset.Ticker or "",
                    side        = side,
                    position    = position,
                    update_type = update_type,
                )
                bridge.on_price_depth(event)

        return _cb

    def _make_progress_callback(self):
        @WINFUNCTYPE(None, TAssetID, c_int)
        def _cb(assetId, nProgress):
            pass  # silencioso; pode logar se necessário
        return _cb

    def _make_tiny_callback(self):
        @WINFUNCTYPE(None, TAssetID, c_double, c_int, c_int)
        def _cb(assetId, price, qtd, side):
            pass  # tratado via book callback
        return _cb

    def _make_price_book_callback(self):
        @WINFUNCTYPE(None, TAssetID, c_int, c_int, c_int, c_int, c_int,
                     c_double, POINTER(c_int), POINTER(c_int))
        def _cb(assetId, nAction, nPosition, side, nQtd, nCount,
                sPrice, pArraySell, pArrayBuy):
            pass  # price book agregado; usamos offer book
        return _cb
