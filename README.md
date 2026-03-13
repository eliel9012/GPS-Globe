# GPS-Globe

## Português

Visualizador web em tempo real para dados GPS/GNSS, com globo 3D, posição atual do receptor e satélites GPS usados no cálculo da posição.

## English

Real-time GPS/GNSS web visualizer with a 3D globe, live receiver position, and GPS satellites used in the positioning solution.

## O que este projeto faz

- Exibe a posição atual do receptor GPS em um globo 3D.
- Mostra os satélites GPS visíveis e os que estão participando do cálculo.
- Permite clicar nos satélites do globo para abrir um tooltip com:
  - foto do bloco/satélite
  - data de lançamento
  - localização orbital atual
  - período orbital
  - velocidade orbital
- Atualiza a interface em tempo real a partir do `gpsd`.
- Usa TLEs operacionais do GPS para calcular subponto orbital e visualização.

## Stack

- Backend: Python 3
- Frontend: HTML, CSS, JavaScript
- Globo 3D: `globe.gl`
- Dados de posição: `gpsd`
- Propagação orbital: `skyfield`

## Estrutura

- [`server.py`](./server.py): servidor HTTP, integração com `gpsd`, TLEs e metadata orbital.
- [`static/index.html`](./static/index.html): estrutura da interface.
- [`static/app.js`](./static/app.js): renderização do globo, polling da API e tooltip dos satélites.
- [`static/styles.css`](./static/styles.css): layout responsivo e identidade visual.
- [`static/assets`](./static/assets): favicon e imagens locais usadas pela UI.

## Como rodar localmente

Pré-requisitos:

- Python 3
- `gpsd` ativo e respondendo
- acesso de rede para baixar TLEs e metadata pública

Execução:

```bash
python3 server.py --host 0.0.0.0 --port 18196
```

Depois abra:

```text
http://127.0.0.1:18196
```

## API

O frontend consome principalmente:

- `GET /api/state`
- `GET /healthz`

## Fontes de dados

- GPS operational TLEs: CelesTrak
- Datas de lançamento dos satélites GPS: QZSS
- Fotos de blocos GPS: GPS.gov

## Licença

MIT. Veja [`LICENSE`](./LICENSE).

## Observações

- Este repositório não inclui config de tunnel nem cache operacional.
- O projeto foi organizado para publicação sem informações sensíveis de infraestrutura pessoal.
