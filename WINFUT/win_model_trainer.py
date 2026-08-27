"""
win_model_trainer.py
Processa o histórico do WINFUT, extrai as features, gera os labels (alvos)
e treina o modelo de Machine Learning.
"""

import sys
import os
import psycopg2
import logging
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
import pickle

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import DB_DSN, PRICE_SCALE_BY_PREFIX
from WINFUT.renko_engine import RenkoEngine
from WINFUT.win_feature_extractor import WinFeatureExtractor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("win_trainer")

def build_dataset(limit=500000):
    log.info("Buscando dados no banco de dados...")
    scale = PRICE_SCALE_BY_PREFIX.get("WIN", 5.0)
    
    extractor = WinFeatureExtractor()
    
    # Closure para interceptar o fechamento do box e extrair features
    # Usamos uma lista para armazenar o timestamp mais recente recebido
    current_ts = [None]
    
    def on_box_close(box):
        if current_ts[0] is not None:
            extractor.extract_on_box_close(box, current_ts[0])

    renko = RenkoEngine(box_size=50.0, sma_period=10, aggression_filter=5000.0, on_box_close=on_box_close)
    
    try:
        with psycopg2.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT ts, price, qty, trade_type
                    FROM trades 
                    WHERE ticker = 'WINFUT'
                    ORDER BY ts ASC
                    LIMIT {limit}
                """)
                
                rows = cur.fetchall()
                if not rows:
                    log.warning("Nenhum dado encontrado.")
                    return None
                    
                log.info(f"Processando {len(rows)} trades para construir features...")
                
                for ts, price_raw, qty, t_type in rows:
                    real_price = float(price_raw) * scale
                    current_ts[0] = ts
                    
                    # Adiciona ao extrator
                    extractor.add_trade(ts, real_price, qty, t_type)
                    
                    # Processa no Renko
                    vol = 0.0
                    if t_type == 2:
                        vol = qty
                    elif t_type == 3:
                        vol = -qty
                    renko.process_trade(real_price, vol)
                    
    except Exception as e:
        log.error(f"Erro no banco: {e}")
        return None
        
    df_features = extractor.get_dataframe()
    if df_features.empty:
        log.warning("Nenhuma feature gerada.")
        return None
        
    log.info(f"Gerado dataset com {len(df_features)} amostras (boxes).")
    
    # Criar o Label (Y): O próximo box continua a tendência?
    # Se estou verde (1) e o proximo box for verde, Sucesso (1). Se for vermelho, Falha (0 = Reversão).
    df_features['next_color'] = df_features['state_color'].shift(-1)
    df_features['target'] = (df_features['state_color'] == df_features['next_color']).astype(int)
    
    # Remover a última linha que não tem 'next_color'
    df_features = df_features.dropna(subset=['next_color'])
    
    # Mostrar contagem de labels para debug
    counts = df_features['target'].value_counts()
    log.info(f"Distribuição de Labels: 1 (Continuação) = {counts.get(1, 0)}, 0 (Reversão) = {counts.get(0, 0)}")
    
    return df_features

def train_model():
    df = build_dataset()
    if df is None or df.empty:
        return
        
    # Selecionar as colunas de treino
    feature_cols = [
        'state_color', 'is_locked', 'dist_to_sma', 
        'trades_per_sec', 'buy_imbalance', 'avg_trade_size', 'large_trades_count'
    ]
    
    X = df[feature_cols]
    y = df['target']
    
    log.info("Treinando RandomForest (com class_weight='balanced_subsample')...")
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
    
    # O balanceamento de classes (class_weight) penaliza mais fortemente os erros 
    # cometidos contra a classe minoritária (0 = Reversão).
    clf = RandomForestClassifier(n_estimators=100, max_depth=5, class_weight='balanced_subsample', random_state=42)
    clf.fit(X_train, y_train)
    
    y_pred = clf.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    log.info(f"Acurácia no Teste (Forward Walk): {acc:.2f}")
    
    report = classification_report(y_test, y_pred)
    print("Relatório de Classificação (Foco na Classe 0 - Reversão):\n", report)
    
    # Salvar o modelo
    model_path = os.path.join(os.path.dirname(__file__), 'win_model.pkl')
    with open(model_path, 'wb') as f:
        pickle.dump(clf, f)
    log.info(f"Modelo salvo em {model_path}")

if __name__ == "__main__":
    train_model()
