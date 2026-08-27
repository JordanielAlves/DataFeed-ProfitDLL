import sys
import os
import psycopg2
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import DB_DSN, PRICE_SCALE_BY_PREFIX
from WINFUT.renko_engine import RenkoEngine

def plot_renko():
    scale = 1.0 # O banco de dados já armazena em pontos reais (Escala 1x para WINFUT)
    renko = RenkoEngine(box_size=50.0, sma_period=10, aggression_filter=5000.0)

    try:
        with psycopg2.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                # Pegamos um trecho do meio do dia
                cur.execute("""
                    SELECT ts, price, qty, trade_type
                    FROM trades 
                    WHERE ticker = 'WINFUT'
                    ORDER BY ts ASC
                    LIMIT 200000
                """)
                rows = cur.fetchall()
                if not rows:
                    print("Nenhum dado encontrado.")
                    return
                
                print("Processando ticks no motor Renko...")
                for ts, price_raw, qty, t_type in rows:
                    real_price = float(price_raw) * scale
                    vol = qty if t_type == 2 else (-qty if t_type == 3 else 0.0)
                    renko.process_trade(real_price, vol)
    except Exception as e:
        print(f"Erro no BD: {e}")
        return

    # Pegar apenas os ultimos 100 boxes gerados para nao poluir a imagem
    boxes = renko.boxes[-100:] if len(renko.boxes) > 100 else renko.boxes
    if not boxes:
        print("Nenhum box gerado.")
        return

    fig, ax = plt.subplots(figsize=(14, 8))
    
    x_vals = []
    sma_vals = []
    
    # Desenhar os boxes
    for i, box in enumerate(boxes):
        # A lógica da cor baseada no state_color do indicador
        face_color = 'green' if box.state_color == 1 else 'red'
        
        # O y do retângulo é sempre o menor valor entre open e close
        y_bottom = min(box.open_price, box.close_price)
        height = abs(box.close_price - box.open_price)
        
        rect = Rectangle((i, y_bottom), 0.8, height, facecolor=face_color, edgecolor='black', linewidth=1)
        ax.add_patch(rect)
        
        # Preparar dados para a linha SMA
        if box.sma is not None:
            x_vals.append(i + 0.4) # Centro do box
            sma_vals.append(box.sma)
            
    # Plotar a linha da Média Móvel
    if x_vals:
        ax.plot(x_vals, sma_vals, color='blue', linewidth=2, label='SMA (10)')
        
    ax.set_xlim(-1, len(boxes))
    
    # Ajustar limites Y
    all_prices = [b.open_price for b in boxes] + [b.close_price for b in boxes]
    if sma_vals:
        all_prices.extend(sma_vals)
    ax.set_ylim(min(all_prices) - 100, max(all_prices) + 100)
    
    ax.set_title("Gráfico Renko 10R - Índice Futuro (WINFUT) com Indicador")
    ax.set_xlabel("Número do Box")
    ax.set_ylabel("Preço (Pontos)")
    ax.grid(True, linestyle='--', alpha=0.6)
    
    # Custom legend
    custom_lines = [
        Line2D([0], [0], color='green', lw=4),
        Line2D([0], [0], color='red', lw=4),
        Line2D([0], [0], color='blue', lw=2)
    ]
    ax.legend(custom_lines, ['Tendência Alta (Verde)', 'Tendência Baixa (Vermelho)', 'SMA 10'])

    output_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'renko_plot.png'))
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Gráfico salvo em: {output_path}")

if __name__ == "__main__":
    plot_renko()
