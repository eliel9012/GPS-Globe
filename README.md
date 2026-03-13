# GPS-Globe

## English

Real-time GPS/GNSS web visualizer with a 3D globe, live receiver position, and clickable GPS satellite metadata.

### Features

- shows the current receiver position on a live 3D globe
- displays GPS satellites used in the positioning solution
- supports clickable satellite tooltips with:
  - launch date
  - current orbital location
  - orbital period
  - speed in km/h
  - local satellite/block image
- updates the interface continuously from `gpsd`
- uses operational GPS TLEs to render orbital context

### Stack

- Python 3
- HTML, CSS, JavaScript
- `globe.gl`
- `gpsd`
- `skyfield`

### Project Structure

- [`server.py`](./server.py): HTTP server, GPS integration, TLE handling, and metadata enrichment
- [`static/index.html`](./static/index.html): page structure
- [`static/app.js`](./static/app.js): globe rendering, polling, and satellite tooltip behavior
- [`static/styles.css`](./static/styles.css): layout and responsive styling
- [`static/assets`](./static/assets): favicon and local satellite images

### Local Run

Requirements:

- Python 3
- `gpsd` running and reachable
- network access for public orbital metadata refresh

Run:

```bash
python3 server.py --host 0.0.0.0 --port 18196
```

Then open:

```text
http://127.0.0.1:18196
```

### API

- `GET /api/state`
- `GET /healthz`

### Data Sources

- GPS operational TLEs: CelesTrak
- GPS launch dates: QZSS
- GPS block photos: GPS.gov

### License

MIT. See [`LICENSE`](./LICENSE).

### Notes

- this repository excludes tunnel configuration and runtime cache
- it was prepared for public release without personal infrastructure secrets

## Português

Visualizador web em tempo real para dados GPS/GNSS, com globo 3D, posição atual do receptor e metadata clicável dos satélites GPS.

### Funcionalidades

- mostra a posição atual do receptor em um globo 3D ao vivo
- exibe os satélites GPS usados no cálculo da posição
- permite clicar nos satélites para abrir tooltip com:
  - data de lançamento
  - localização orbital atual
  - período orbital
  - velocidade em km/h
  - imagem local do bloco/satélite
- atualiza a interface continuamente a partir do `gpsd`
- usa TLEs operacionais do GPS para renderizar o contexto orbital

### Stack

- Python 3
- HTML, CSS, JavaScript
- `globe.gl`
- `gpsd`
- `skyfield`

### Estrutura do Projeto

- [`server.py`](./server.py): servidor HTTP, integração com GPS, TLEs e enriquecimento de metadata
- [`static/index.html`](./static/index.html): estrutura da página
- [`static/app.js`](./static/app.js): renderização do globo, polling e comportamento do tooltip
- [`static/styles.css`](./static/styles.css): layout e responsividade
- [`static/assets`](./static/assets): favicon e imagens locais dos satélites

### Execução Local

Requisitos:

- Python 3
- `gpsd` ativo e acessível
- acesso de rede para atualização pública de metadata orbital

Execução:

```bash
python3 server.py --host 0.0.0.0 --port 18196
```

Depois abra:

```text
http://127.0.0.1:18196
```

### API

- `GET /api/state`
- `GET /healthz`

### Fontes de Dados

- TLEs operacionais do GPS: CelesTrak
- datas de lançamento dos satélites GPS: QZSS
- fotos dos blocos GPS: GPS.gov

### Licença

MIT. Veja [`LICENSE`](./LICENSE).

### Observações

- este repositório não inclui configuração de tunnel nem cache de runtime
- ele foi preparado para publicação pública sem segredos de infraestrutura pessoal
