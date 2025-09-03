import pandas as pd
import streamlit as st

st.set_page_config(page_title="Controle de Reparos", page_icon= "⚒️", layout= "wide", initial_sidebar_state="expanded")

def leitura_dados():
    colunas_importantes = [
        "Status","Sit","Prefixo","Or?/OS","Item",
        "P/N Compras","P/N Removido","S/N Removido",
        "Insumo","Grupo","Enviar at?","Retornar at?",
        "Motivo","Condi??o","Qtdade"
    ]

    dados = pd.read_excel(
        "reparo_atual.xlsx",
        sheet_name="Worksheet",
        usecols=colunas_importantes
    )

    for col in ["Enviar at?", "Retornar at?"]:
        if col in dados.columns:
            dados[col] = pd.to_datetime(dados[col], dayfirst=True, errors="coerce")

    dados.to_csv("reparo_atual_csv.csv", sep=';', index= False, encoding="utf-8")

    return dados

dados = leitura_dados()
print(dados)
