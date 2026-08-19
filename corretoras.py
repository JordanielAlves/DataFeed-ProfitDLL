"""
corretoras.py
Módulo centralizado de mapeamento de Códigos de Corretoras B3 para Nomes Reduzidos.
Utilizado por todos os relatórios, motores quantitativos (ML) e alertas do ProfitDLL.
"""

CORRETORAS_B3 = {
    1: "Banco do Brasil",
    3: "XP",
    4: "Alfa",
    7: "Credicoamo",
    8: "UBS",
    10: "Pátria",
    12: "Hencorp",
    13: "Merrill Lynch",
    14: "Deltapart",
    15: "Guide",
    16: "J.P. Morgan",
    18: "Bacor",
    19: "Magliano",
    21: "Intercap",
    23: "Modal / Necton",
    24: "Flow",
    25: "Banco Bocom BBM",
    27: "Santander",
    33: "Sólidez",
    35: "Leme",
    38: "Órama",
    39: "Ágora",
    40: "Morgan",
    43: "Siti",
    45: "Credialiança",
    48: "CM Capital",
    51: "RJI",
    58: "Geração Futuro",
    59: "Solvi",
    61: "Vítor",
    62: "GTI",
    70: "Planner",
    72: "Bradesco",
    73: "Bunge",
    77: "Singulare",
    83: "Socopa",
    85: "BTG",
    88: "Mirae",
    89: "Corretora Geral",
    90: "Espinosa",
    92: "Renascença",
    93: "Nova Futura",
    95: "Safra",
    99: "Levy Camargo",
    102: "Sociedade",
    107: "Terra",
    109: "Simoes",
    113: "Magliano",
    114: "Citi",
    115: "Itaú",
    120: "Genial",
    122: "BGC Liquidez",
    127: "Tullett",
    131: "Fator",
    140: "Elite",
    147: "Ativa",
    165: "Empe",
    172: "Banrisul",
    174: "Sita",
    182: "Cruzeiro do Sul",
    186: "Lê",
    189: "Ametista",
    195: "RCO",
    198: "Cacique",
    211: "Tuchê",
    226: "Amaril",
    238: "Goldman",
    241: "Unibanco",
    251: "BNP",
    254: "BB",
    262: "Mundo",
    275: "Dillinger",
    308: "HCommex",
    310: "Bancorbrás",
    379: "Votorantim",
    386: "Nossa Caixa",
    688: "ABN",
    740: "Toro",
    1026: "BTG Banco",
    1081: "BancoSeguro",
    1110: "Inter",
    1408: "Clear",
    1618: "Ideal",
    1931: "Rico",
    2659: "BB",
    4002: "Andbank",
    4090: "Nu Invest",
    5264: "ASA",
    6003: "C6",
    8500: "C6 Bank"
}


def get_nome_corretora(agent_id: int | str) -> str:
    """
    Retorna apenas o Nome Reduzido da corretora. Exemplo: 85 -> 'BTG'
    Se não encontrar, retorna a string do próprio código.
    """
    try:
        codigo = int(agent_id)
        return CORRETORAS_B3.get(codigo, str(agent_id))
    except (ValueError, TypeError):
        return str(agent_id)


def get_corretora_label(agent_id: int | str) -> str:
    """
    Retorna o Nome Reduzido acompanhado do código. Exemplo: 85 -> 'BTG (85)'
    Se o código não estiver mapeado, retorna apenas o código como 'Corretora X'.
    """
    try:
        codigo = int(agent_id)
        if codigo in CORRETORAS_B3:
            return f"{CORRETORAS_B3[codigo]} ({codigo})"
        return f"Corretora {codigo}"
    except (ValueError, TypeError):
        return f"Corretora {agent_id}"
