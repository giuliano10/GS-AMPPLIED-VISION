# Triagem de barreiras de acessibilidade (VS Code / Python)

Programa desktop que analisa foto, vídeo ou câmera ao vivo e desenha caixas com rótulos em português, confiança e o possível impacto na circulação.
Usa o **modelo RF-DETR treinado por nós no Roboflow**, junto com um YOLO pré-treinado para objetos comuns de via.
Também resume se há obstáculo na via e se existe uma possível passagem.
É uma **triagem visual sujeita a erros**, não uma avaliação oficial de acessibilidade.

## Instalação (Windows, PowerShell)
Requer **Python 3.10 a 3.12** (o pacote `inference` não funciona no 3.13+).
```
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1        # se der erro de política: Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements.txt     # demora: o pacote 'inference' é grande
python main.py
```
Na primeira execução o programa abre uma janelinha pedindo o **ID do modelo** (já vem preenchido) e a **chave privada** do Roboflow
(Settings > API Keys). Os dados são salvos no arquivo `.env`, só neste computador; nas próximas vezes nada é perguntado.
Para trocar a chave ou o modelo, use o botão **"Configurar chave do Roboflow…"**. O modelo é baixado na 1ª execução (precisa de internet) e depois roda offline.
Nenhuma imagem é enviada, e só é salva se você escolher "Salvar quadro" no menu de botão direito.

## Segurança da chave (projeto público)
- **Nunca coloque a chave no código, no README nem em commits.** Ela fica só no `.env`, que está no `.gitignore`.
- Antes de publicar, rode `git status` e confirme que `.env` não aparece na lista. O ID do modelo não é segredo; a chave é.
- Quem executar o trabalho cria a própria chave e informa na janelinha da 1ª execução. Se a chave vazar, gere outra no Roboflow e apague a antiga.
- Variáveis do terminal (`$env:ROBOFLOW_API_KEY=...`) têm prioridade sobre o `.env`.

## Modos de detecção
- **Híbrido (padrão):** seu modelo + YOLO pré-treinado (COCO, `yolov8n.pt`, baixado na 1ª vez). O YOLO só contribui com objetos comuns de via (bicicleta, carro, moto, ônibus, caminhão, banco, hidrante, parquímetro, placa, semáforo), sempre como "obstáculo". Caixas do YOLO que repetem um obstáculo já achado pelo seu modelo são descartadas. Pessoas nunca entram.
- **Só meu modelo:** apenas o RF-DETR do Roboflow.
- **Só YOLO:** apenas o YOLO. Não conhece buraco, rachadura, lixo nem piso tátil; serve para comparar os três modos nas mesmas fotos.
Se o YOLO não puder ser carregado, o Híbrido continua só com o seu modelo e avisa na tela. A lista de objetos do YOLO e a confiança mínima dele (`yolo_conf_min`) ficam em `models/config.json`. Com os dois modelos, a câmera fica mais lenta.

## Uso
Escolher foto/vídeo, iniciar/parar câmera, escolher o modo e ajustar a confiança mínima (painel à direita). Botão direito sobre a imagem: salvar quadro, copiar lista, ocultar categoria, mostrar ocultas, pausar/retomar.

## Classes e mapeamento
Os nomes das classes do projeto Roboflow são convertidos para as categorias do programa por `mapa_classes_roboflow` em `models/config.json`.
Classes sem mapeamento são ignoradas e o programa avisa quais; acrescente-as no mapa. Pessoas nunca são rotuladas.

## Melhorar o modelo
Adicione fotos ao mesmo projeto no Roboflow (inclusive fotos sem barreiras, marcadas como Null), anote, crie uma nova versão e treine de novo.
Depois altere `roboflow_modelo_id` em `models/config.json` (ou use o botão de configuração) para a nova versão, por exemplo `gs-vision-0vry7/5`. Teste sempre com fotos que não foram usadas no treino.

## Limites
- A "possível passagem" é uma estimativa geométrica com as caixas detectadas; não confirma piso transitável nem a largura real.
- Só detecta o que os modelos foram treinados para ver; a ausência de detecção não garante via livre.

## Estrutura
```
main.py  requirements.txt  models/config.json  .vscode/launch.json  .gitignore  README.md
```
