import re
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
import os

# --- CONFIGURAÇÃO ---
# Adicionei o .txt pois seu Windows mostra "Documento de Texto"
LOG_FILE = 'execution_log.txt' 

def parse_log(file_path):
    data = []
    
    # Se não achar com .txt, tenta sem a extensão por garantia
    if not os.path.exists(file_path):
        if os.path.exists('execution_log'):
            file_path = 'execution_log'
        else:
            print(f"ERRO CRÍTICO: Não encontrei o arquivo '{file_path}' nem 'execution_log'.")
            print("Verifique se o arquivo está na mesma pasta que este script.")
            return None

    print(f"Lendo o arquivo: {file_path}...")
    
    # Regex ajustado para o seu formato de log
    log_pattern = re.compile(r'\[(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})\]\s\[INFO\]\s(.*)')
    
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            match = log_pattern.match(line)
            if match:
                timestamp_str = match.group(1)
                message = match.group(2)
                
                try:
                    dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    continue
                
                event_type = None
                if 'SKU ID:' in message:
                    event_type = 'sku_processed'
                elif '[OK] Image updated:' in message:
                    event_type = 'image_updated'
                
                if event_type:
                    data.append({'timestamp': dt, 'type': event_type})

    return pd.DataFrame(data)

def generate_charts(df):
    if df.empty:
        print("O arquivo foi lido, mas nenhum dado relevante (SKU ou Image Updated) foi encontrado.")
        return

    df.set_index('timestamp', inplace=True)

    # Reamostragem por minuto
    resampled = df.groupby('type').resample('1min').size().unstack(level=0).fillna(0)

    # Configuração do gráfico
    plt.style.use('bmh')
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)

    # Gráfico 1: Velocidade
    if 'sku_processed' in resampled.columns:
        ax1.plot(resampled.index, resampled['sku_processed'], label='SKUs Lidos/Min', color='#1f77b4')
    if 'image_updated' in resampled.columns:
        ax1.plot(resampled.index, resampled['image_updated'], label='Imagens Atualizadas/Min', color='#2ca02c')
    
    ax1.set_title('Velocidade de Processamento')
    ax1.set_ylabel('Qtd por Minuto')
    ax1.legend()
    ax1.grid(True)  # Corrigido aqui

    # Gráfico 2: Acumulado
    cumulative = resampled.cumsum()
    
    if 'sku_processed' in cumulative.columns:
        ax2.fill_between(cumulative.index, cumulative['sku_processed'], label='Total SKUs', color='#1f77b4', alpha=0.3)
    if 'image_updated' in cumulative.columns:
        ax2.plot(cumulative.index, cumulative['image_updated'], label='Total Imagens', color='#2ca02c', linewidth=2)

    ax2.set_title('Progresso Total')
    ax2.set_ylabel('Total Acumulado')
    ax2.set_xlabel('Horário')
    ax2.legend()
    ax2.grid(True)

    plt.tight_layout()
    plt.savefig('grafico_performance.png')
    print("Sucesso! Gráfico salvo como 'grafico_performance.png'")
    plt.show()

if __name__ == "__main__":
    df_log = parse_log(LOG_FILE)
    if df_log is not None:
        generate_charts(df_log)