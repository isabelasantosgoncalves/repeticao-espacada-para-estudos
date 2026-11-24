"""
Dados de exemplo para a conta demo (demo@demo.com / demo123).

As sessões são geradas simulando um estudante que segue o próprio algoritmo:
cada assunto começa em uma data, melhora aos poucos e volta na data de revisão
sugerida (às vezes com alguns dias de atraso). Usa uma semente fixa, então o
resultado é sempre parecido.
"""

import random
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

import logica as L

DEMO = ("Estudante Demo", "demo@demo.com", "demo123")

# matéria -> [(assunto, dias atrás do início ou None = nunca estudado, nível inicial, ganho por sessão)]
#            ou (assunto, [subassuntos no mesmo formato])
CURRICULO = {
    "Matemática": [
        ("Funções do 1º grau", 70, 0.55, 0.12),
        ("Porcentagem", 52, 0.70, 0.08),
        ("Geometria plana", 30, 0.35, 0.10),
        ("Probabilidade", 1, 0.45, 0.10),
        ("Logaritmos", None, 0, 0),
        # Assunto com subassuntos: cada um tem o próprio domínio
        ("Álgebra", [
            ("Equações do 1º grau", 50, 0.80, 0.06),
            ("Inequações", 24, 0.35, 0.07),
            ("Sistemas lineares", 14, 0.55, 0.10),
            ("Problemas com equações", None, 0, 0),
        ]),
    ],
    "Português": [
        ("Crase", 60, 0.40, 0.15),
        ("Concordância verbal", 40, 0.60, 0.07),
        ("Interpretação de texto", 85, 0.75, 0.06),
        ("Regência", None, 0, 0),
    ],
    "Biologia": [
        ("Citologia", 45, 0.50, 0.10),
        ("Genética", 21, 0.30, 0.12),
        ("Ecologia", None, 0, 0),
    ],
    "História": [
        ("Brasil Colônia", 75, 0.65, 0.09),
        ("Era Vargas", 26, 0.45, 0.06),
        ("Revolução Industrial", None, 0, 0),
    ],
}

# Seção de exemplo: todas as matérias do currículo, com prova só com o mês.
SECAO = ("ENEM", "{ano}-11")

# Flashcards de exemplo: matéria -> baralho -> [(frente, verso, [(dias atrás, resposta), ...])]
# Sem respostas = cartão novo. Com a fase padrão (7 e 15 dias), alguns vencem hoje.
BARALHOS = {
    "Matemática": {
        "Fórmulas": [
            ("Fórmula de Bhaskara", r"$$x = \frac{-b \pm \sqrt{\Delta}}{2a}$$", [(7, "acertei")]),
            ("Discriminante (Δ)", r"$$\Delta = b^2 - 4ac$$", [(22, "acertei"), (15, "acertei")]),
            ("Área do círculo", r"$$A = \pi r^2$$", [(3, "acertei")]),
            ("Volume do cilindro", "V = πr²h", [(1, "errei")]),
            ("Soma dos ângulos internos de um polígono", "S = (n − 2) · 180°", []),
            ("Termo geral da PA", "aₙ = a₁ + (n − 1) · r", []),
        ],
    },
    "Português": {
        "Crase": [
            ("Crase antes de palavra masculina?", "Não. Ex.: andar a pé, a cavalo.", [(2, "demorei")]),
            ("Crase em “à moda de”", "Sim, mesmo com a palavra omitida: bife à milanesa.", [(7, "acertei")]),
            ("Crase antes de verbo?", "Nunca. Ex.: começou a estudar.", []),
        ],
    },
    "Biologia": {
        "Organelas": [
            ("Mitocôndria", "Respiração celular: produz ATP.", [(20, "acertei"), (13, "errei"), (12, "acertei")]),
            ("Ribossomo", "Síntese de proteínas.", [(4, "acertei")]),
            ("Complexo golgiense", "Modifica, armazena e exporta substâncias (secreção).", []),
        ],
    },
}

# Cartões que também perguntam ao contrário (verso -> frente)
INVERTIDOS = {"Mitocôndria", "Ribossomo"}

OBSERVACOES = [
    None, None, None,
    "Errei por falta de atenção no enunciado.",
    "Revisar a teoria antes da próxima.",
    "Questões da banca mais difíceis.",
    "Fiz com tempo cronometrado.",
    "Melhorou bastante depois do resumo.",
]


def simular(inicio: date, hoje: date, nivel: float, ganho: float, rnd: random.Random):
    """Gera sessões (data, acertos, total) seguindo as datas que o algoritmo sugere."""
    sessoes = []
    d = inicio
    while d < hoje:
        pcts = [L.percentual(a, t) for _, a, t in sessoes]
        totais = [t for _, _, t in sessoes]
        total = L.questoes_sugeridas(L.dominio(pcts, totais)) if pcts else 20
        chance = min(0.98, max(0.1, nivel + rnd.uniform(-0.12, 0.08)))
        acertos = sum(1 for _ in range(total) if rnd.random() < chance)
        sessoes.append((d, acertos, total))
        nivel = min(0.97, nivel + ganho * rnd.uniform(0.5, 1.2))
        intervalo, _ = L.calcular_intervalo(pcts + [acertos / total], totais + [total])
        # às vezes o estudante atrasa a revisão
        atraso = rnd.choice([0, 0, 0, 1, 2, 5, 9])
        d = d + timedelta(days=intervalo + atraso)
    return sessoes


def criar_assunto(con, uid, mid, item, hoje, rnd, pai=None) -> int:
    """Cria um assunto (ou subassunto) e suas sessões simuladas. Devolve quantas sessões."""
    nome, dias_atras, nivel, ganho = item
    aid = con.execute("INSERT INTO assuntos (usuario_id, materia_id, nome, parent_id) VALUES (?, ?, ?, ?)",
                      (uid, mid, nome, pai)).lastrowid
    if dias_atras is None:
        return 0
    inicio = hoje - timedelta(days=dias_atras)
    n = 0
    for d, acertos, total in simular(inicio, hoje, nivel, ganho, rnd):
        con.execute(
            """INSERT INTO sessoes (usuario_id, assunto_id, data, acertos, total, observacao)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (uid, aid, d.isoformat(), acertos, total, rnd.choice(OBSERVACOES)))
        n += 1
    return n


def criar_demo(con, hoje: date) -> int:
    """Apaga e recria a conta demo. Devolve o número de sessões criadas."""
    nome, email, senha = DEMO
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("DELETE FROM usuarios WHERE email = ?", (email,))
    uid = con.execute(
        "INSERT INTO usuarios (nome, email, senha_hash, onboarding_ok) VALUES (?, ?, ?, 1)",
        (nome, email, generate_password_hash(senha))).lastrowid
    con.execute(
        """INSERT INTO configuracoes (usuario_id, modo, dias_fixos, revisao_minima, questoes_modo, questoes_fixas)
           VALUES (?, 'ambos', '6', 3, 'auto', 10)""", (uid,))

    rnd = random.Random(2026)
    n = 0
    ids = {}
    sid = con.execute("INSERT INTO secoes (usuario_id, nome, data_meta) VALUES (?, ?, ?)",
                      (uid, SECAO[0], SECAO[1].format(ano=hoje.year + 1))).lastrowid
    for materia, assuntos in CURRICULO.items():
        mid = con.execute("INSERT INTO materias (usuario_id, nome, secao_id) VALUES (?, ?, ?)",
                          (uid, materia, sid)).lastrowid
        ids[materia] = mid
        for item in assuntos:
            if isinstance(item[1], list):
                pai = con.execute("INSERT INTO assuntos (usuario_id, materia_id, nome) VALUES (?, ?, ?)",
                                  (uid, mid, item[0])).lastrowid
                for sub in item[1]:
                    n += criar_assunto(con, uid, mid, sub, hoje, rnd, pai)
            else:
                n += criar_assunto(con, uid, mid, item, hoje, rnd)
    criar_flashcards(con, uid, ids, hoje)
    con.commit()
    return n


def criar_flashcards(con, uid, ids: dict, hoje: date):
    """Baralhos de exemplo: alguns cartões já respondidos (alguns vencem hoje) e alguns novos."""
    for materia, baralhos in BARALHOS.items():
        for nome, cartoes in baralhos.items():
            bid = con.execute("INSERT INTO baralhos (usuario_id, materia_id, nome) VALUES (?, ?, ?)",
                              (uid, ids[materia], nome)).lastrowid
            for frente, verso, respostas in cartoes:
                cid = con.execute("INSERT INTO cartoes (usuario_id, baralho_id, frente, verso, invertido) VALUES (?, ?, ?, ?, ?)",
                                  (uid, bid, frente, verso, int(frente in INVERTIDOS))).lastrowid
                for dias_atras, nota in respostas:
                    con.execute("INSERT INTO respostas_cartao (usuario_id, cartao_id, data, nota) VALUES (?, ?, ?, ?)",
                                (uid, cid, (hoje - timedelta(days=dias_atras)).isoformat(), nota))
