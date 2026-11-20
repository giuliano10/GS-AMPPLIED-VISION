"""Triagem visual de barreiras de acessibilidade (YOLO + OpenCV + Tkinter).
Processamento 100% local. Nada é salvo sem o usuário pedir. Resultado é triagem, não laudo oficial."""
import json, os, queue, threading, time, tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox, simpledialog
import cv2, numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

BASE = Path(__file__).parent
def _carregar_env():
    """Lê KEY=valor de um arquivo .env local (nunca versionado) sem sobrescrever variáveis já definidas no terminal."""
    f = BASE / ".env"
    if not f.exists(): return
    for linha in f.read_text(encoding="utf-8-sig").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            k, v = linha.split("=", 1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
_carregar_env()
def _gravar_env(**dados):
    """Grava/atualiza chaves no arquivo .env local (que está no .gitignore) e também no ambiente atual."""
    f = BASE / ".env"; linhas = f.read_text(encoding="utf-8-sig").splitlines() if f.exists() else []
    for k, v in dados.items():
        os.environ[k] = v; nova = f"{k}={v}"
        for i, l in enumerate(linhas):
            if l.split("=", 1)[0].strip() == k: linhas[i] = nova; break
        else: linhas.append(nova)
    f.write_text("\n".join(linhas) + "\n", encoding="utf-8")
CFG = {  # configuração padrão embutida; models/config.json (opcional) sobrescreve
  "roboflow_modelo_id": "",
  "mapa_classes_roboflow": {"buraco": "buraco", "pothole": "buraco", "rachadura": "rachadura", "crack": "rachadura", "obstaculo": "obstaculo", "obstáculo": "obstaculo",
    "obstacle": "obstaculo", "lixo": "obstaculo", "saco de lixo": "obstaculo", "garbage": "obstaculo", "trash": "obstaculo", "calcada_quebrada": "calcada_quebrada",
    "calçada quebrada": "calcada_quebrada", "desnivel": "desnivel", "desnível": "desnivel", "piso_tatil_interrompido": "piso_tatil_interrompido",
    "passagem_bloqueada": "passagem_bloqueada", "passagem_estreita": "passagem_estreita", "obstaculo_suspenso": "obstaculo_suspenso",
    "carro": "obstaculo", "moto": "obstaculo", "bicicleta": "obstaculo"},
  "modelo_yolo": "yolov8n.pt", "yolo_conf_min": 0.3,
  "yolo_obstaculos": ["bicycle", "motorcycle", "car", "truck", "bus", "bench", "fire hydrant", "parking meter", "stop sign", "traffic light"]}
try:
    for _k, _v in json.loads((BASE / "models" / "config.json").read_text(encoding="utf-8")).items():
        if isinstance(_v, dict) and isinstance(CFG.get(_k), dict): CFG[_k].update(_v)
        else: CFG[_k] = _v
except FileNotFoundError: pass
except (json.JSONDecodeError, OSError) as _e: print(f"Aviso: config.json inválido ({_e}); usando padrão.")
CATS = {  # chave: (nome, cor, impacto)
 "buraco": ("buraco", "#e63946", "Pode causar quedas e travar rodas de cadeira ou bengala."),
 "rachadura": ("rachadura", "#f4a261", "Pode prender rodízios e atrapalhar a leitura do piso com bengala."),
 "desnivel": ("desnível", "#ff7b00", "Degrau ou rampa irregular: impede ou arrisca a passagem de cadeira de rodas."),
 "calcada_quebrada": ("calçada quebrada", "#d00070", "Piso solto ou irregular: risco de tropeço e de travar rodas."),
 "obstaculo": ("obstáculo", "#2a9d8f", "Objeto no caminho: exige desvio e pode não ser percebido por quem usa bengala."),
 "passagem_bloqueada": ("passagem bloqueada", "#7b2cbf", "Pode impedir totalmente a circulação."),
 "piso_tatil_interrompido": ("piso tátil interrompido", "#1d6fe0", "A guia para pessoas cegas ou com baixa visão se perde."),
 "passagem_estreita": ("passagem estreita", "#6a994e", "Largura livre pode ser menor que a necessária para cadeira de rodas."),
 "obstaculo_suspenso": ("obstáculo suspenso", "#8d5a97", "Acima da altura da bengala: risco de colisão para pessoas com deficiência visual."),
}
_fontes = {}
def fonte(tam):
    if tam not in _fontes:
        for n in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
            try: _fontes[tam] = ImageFont.truetype(n, tam); break
            except OSError: pass
        else: _fontes[tam] = ImageFont.load_default()
    return _fontes[tam]

def rotulo(d): return CATS[d['cat']][0]  # não especifica o tipo de objeto

def compor(img, dets, ocultas, esc=1.0, pas=None):
    dr = ImageDraw.Draw(img); e = max(1, img.width / 800); f = fonte(int(14 * e))
    for d in dets:
        if d["cat"] in ocultas: continue
        x1, y1, x2, y2 = [v * esc for v in d["box"]]; cor = CATS[d["cat"]][1]
        dr.rectangle([x1, y1, x2, y2], outline=cor, width=max(2, int(3 * e)))
        t = f"{rotulo(d)} {round(d['conf'] * 100)}%"; l, t0, r, b = dr.textbbox((0, 0), t, font=f)
        w, h = r - l + 8, b - t0 + 6; ty = y1 - h if y1 > h else y1
        lx = max(0, min(x1, img.width - w)); dr.rectangle([lx, ty, lx + w, ty + h], fill=cor); dr.text((lx + 4, ty + 2), t, font=f, fill="white")
    if pas:  # faixa verde na base da imagem = possível passagem
        hh = int(20 * e); x1, x2 = pas[0] * esc, pas[1] * esc
        dr.rectangle([x1, img.height - hh, x2, img.height], fill="#2e9e4f"); dr.text((x1 + 4, img.height - hh + 2), "possível passagem", font=f, fill="white")
    return img

def resumo(dets, ocultas, w, h, modo="hib"):
    """Diz se há obstáculo e se há possível passagem. Estimativa geométrica só com as caixas detectadas:
    NÃO verifica se o piso é transitável nem a largura real."""
    v = [d for d in dets if d["cat"] not in ocultas]
    if not v:
        if modo == "yolo": return "Nenhum objeto comum detectado. Este modo NÃO vê buracos, lixo nem piso tátil.", None
        return "Nenhum obstáculo detectado pelo modelo (confira no local).", None
    base = f"Obstáculo detectado na via ({len(v)})."
    if modo == "yolo": return base + " Passagem não avaliada neste modo (use Híbrido ou Meu modelo).", None
    blocos = sorted((d["box"][0], d["box"][2]) for d in v if d["box"][3] >= 0.4 * h)  # só os mais próximos (parte de baixo da imagem)
    if not blocos: return base + " Nenhum próximo; via aparentemente livre à frente.", None
    livres, x = [], 0
    for a, b in blocos:
        if a > x: livres.append((x, a))
        x = max(x, b)
    if x < w: livres.append((x, w))
    g = max(livres, key=lambda t: t[1] - t[0], default=None)
    if not g or g[1] - g[0] < 0.2 * w: return base + " Sem passagem livre aparente.", None
    c = (g[0] + g[1]) / 2; pos = "à esquerda" if c < w / 3 else "à direita" if c > 2 * w / 3 else "ao centro"
    return base + f" Possível passagem {pos} (~{round((g[1] - g[0]) / w * 100)}% da largura).", g

def sobrepoe(a, b, t=0.5):
    """True se a interseção cobre >= t da menor das duas caixas (usado para descartar detecções duplicadas)."""
    x = max(0, min(a[2], b[2]) - max(a[0], b[0])); y = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    menor = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return menor > 0 and x * y / menor >= t

class Detector:
    """Meu modelo = RF-DETR treinado no Roboflow (pacote 'inference'); YOLO = modelo pré-treinado COCO só para objetos comuns de via."""
    def __init__(s): s.modelo = None; s.yolo = None; s.yolo_erro = ""; s.ignoradas = set(); s.aviso = ""
    def carregar(s):
        if s.modelo is not None: return s.modelo
        mid = os.getenv("ROBOFLOW_MODEL_ID") or CFG["roboflow_modelo_id"]; chave = os.getenv("ROBOFLOW_API_KEY")
        if not mid or not chave: raise RuntimeError("Faltam o ID do modelo e/ou a chave do Roboflow. Use o botão 'Configurar chave do Roboflow…'.")
        try:
            from inference import get_model
            s.modelo = get_model(model_id=mid, api_key=chave)
        except ImportError: raise RuntimeError("Pacote 'inference' não instalado. Use Python 3.10 a 3.12 e rode: pip install -r requirements.txt")
        except Exception as e: raise RuntimeError(f"Não foi possível carregar o modelo Roboflow (precisa de internet na 1ª vez; confira o ID e a chave): {e}" + (" Use o botão 'Configurar chave do Roboflow…' para corrigir." if "nauthorized" in str(e) or "API key" in str(e) else ""))
        return s.modelo
    def carregar_yolo(s):
        if s.yolo is not None: return s.yolo
        if s.yolo_erro: raise RuntimeError(s.yolo_erro)
        try:
            try: from ultralytics import YOLO
            except ImportError: raise RuntimeError("Pacote 'ultralytics' não instalado. Rode: pip install ultralytics")
            try: s.yolo = YOLO(CFG["modelo_yolo"])
            except Exception as e: raise RuntimeError(f"Não foi possível carregar o YOLO ({CFG['modelo_yolo']}); precisa de internet na 1ª vez: {e}")
        except RuntimeError as e: s.yolo_erro = str(e); raise
        return s.yolo
    def det_rf(s, bgr, conf):
        r = s.carregar().infer(bgr, confidence=conf)[0]; out = []; s.ignoradas = set()
        for p in r.predictions:
            nome = str(p.class_name).strip().lower()
            if nome in ("person", "pessoa"): continue  # pessoas nunca são rotuladas
            cat = CFG["mapa_classes_roboflow"].get(nome, nome)
            if cat not in CATS: s.ignoradas.add(str(p.class_name)); continue
            out.append(dict(cat=cat, conf=float(p.confidence), fonte="rf", box=[p.x - p.width / 2, p.y - p.height / 2, p.x + p.width / 2, p.y + p.height / 2]))
        return out
    def det_yolo(s, bgr, conf):
        r = s.carregar_yolo().predict(bgr, conf=max(conf, CFG["yolo_conf_min"]), verbose=False)[0]; ok = set(CFG["yolo_obstaculos"]); out = []
        for b in r.boxes:  # só objetos comuns de via; "person" nunca entra
            if r.names[int(b.cls)] in ok: out.append(dict(cat="obstaculo", conf=float(b.conf), fonte="yolo", box=b.xyxy[0].tolist()))
        return out
    def detectar(s, bgr, conf, modo="hib"):
        s.aviso = ""
        if modo == "yolo": return s.det_yolo(bgr, conf)
        rf = s.det_rf(bgr, conf)
        if modo == "rf": return rf
        try: extra = s.det_yolo(bgr, conf)
        except RuntimeError as e: s.aviso = f"YOLO indisponível; usando só o seu modelo. {e}"; return rf
        base = [d for d in rf if d["cat"] == "obstaculo"]
        return rf + [y for y in extra if not any(sobrepoe(y["box"], d["box"]) for d in base)]

class App:
    def __init__(s, root):
        s.root = root; root.title("Triagem de barreiras de acessibilidade"); root.geometry("1180x720")
        s.det = Detector(); s.fila = queue.Queue(); s.trava = threading.Lock()
        s.parar = threading.Event(); s.sujo = threading.Event(); s.thread = None
        s.ultimo = None; s.mostrado = None; s.ocultas = set(); s.pausado = False; s.conf = 0.5
        s.modo = tk.StringVar(value="hib"); s.cam_ativa = False; s.exib = (1, 0, 0); s.ult_lista = 0
        lado = ttk.Frame(root, padding=8); lado.pack(side="right", fill="y")
        s.vis = tk.Label(root, bg="#14202c", fg="#d9d6cd", text="Escolha uma foto ou vídeo, ou inicie a câmera.")
        s.vis.pack(side="left", fill="both", expand=True)
        ttk.Button(lado, text="Escolher foto ou vídeo", command=s.abrir).pack(fill="x", pady=2)
        s.bcam = ttk.Button(lado, text="Iniciar câmera", command=s.alternar_cam); s.bcam.pack(fill="x", pady=2)
        ttk.Button(lado, text="Configurar chave do Roboflow…", command=lambda: s.configurar(True)).pack(fill="x", pady=2)
        ttk.Label(lado, text="Detecção:", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(8, 0))
        for v, t in (("hib", "Híbrido: meu modelo + YOLO"), ("rf", "Só meu modelo (Roboflow RF-DETR)"), ("yolo", "Só YOLO (objetos comuns)")):
            ttk.Radiobutton(lado, text=t, variable=s.modo, value=v, command=s.mudou).pack(anchor="w")
        s.lim = ttk.Label(lado, text="Confiança mínima: 50%"); s.lim.pack(anchor="w", pady=(8, 0))
        ttk.Scale(lado, from_=10, to=95, value=50, command=s.set_conf).pack(fill="x")
        s.status = tk.Label(lado, text="", wraplength=290, justify="left", fg="#3b4b5b"); s.status.pack(anchor="w", pady=6)
        s.res = tk.Label(lado, text="", wraplength=290, justify="left", font=("TkDefaultFont", 11, "bold")); s.res.pack(anchor="w", pady=4)
        s.lista = tk.Text(lado, width=40, height=22, wrap="word", state="disabled", bg="#fff"); s.lista.pack(fill="both", expand=True)
        s.mudou()
        s.menu = tk.Menu(root, tearoff=0)
        for t, c in (("Salvar quadro com caixas…", s.salvar), ("Copiar lista de achados", s.copiar), ("Ocultar categoria sob o cursor", s.ocultar),
                     ("Mostrar categorias ocultas", lambda: (s.ocultas.clear(), s.redesenhar())), ("Pausar / retomar análise", s.pausar)):
            s.menu.add_command(label=t, command=c)
        for ev in ("<Button-3>", "<Button-2>", "<Control-Button-1>"): s.vis.bind(ev, s.menu_ctx)
        root.protocol("WM_DELETE_WINDOW", s.fechar); root.after(30, s.tick); root.after(400, s.configurar)

    def configurar(s, forcar=False):
        """Pede ID do modelo e chave do Roboflow (na 1ª execução ou pelo botão) e grava no .env local, que não vai para o GitHub."""
        mid = os.getenv("ROBOFLOW_MODEL_ID") or CFG["roboflow_modelo_id"]; chave = os.getenv("ROBOFLOW_API_KEY"); novos = {}
        if forcar or not mid:
            r = simpledialog.askstring("Modelo Roboflow", "ID do modelo (projeto/versão), ex.: gs-vision-0vry7/4", initialvalue=mid or "", parent=s.root)
            if r and r.strip(): novos["ROBOFLOW_MODEL_ID"] = r.strip()
        if forcar or not chave:
            r = simpledialog.askstring("Chave do Roboflow", "Cole a chave PRIVADA (API key) do Roboflow.\nEla fica salva só neste computador, no arquivo .env:", show="*", parent=s.root)
            if r and r.strip(): novos["ROBOFLOW_API_KEY"] = r.strip()
        if novos:
            try: _gravar_env(**novos); s.det.modelo = None; s.msg("Credenciais salvas no arquivo .env (somente neste computador)."); s.sujo.set()
            except OSError as e: s.msg(f"Não foi possível salvar o .env: {e}", True)
        elif not (mid and chave): s.msg("Faltam o ID do modelo e/ou a chave do Roboflow. Use o botão 'Configurar chave do Roboflow…'.", True)
    def msg(s, t, erro=False): s.status.config(text=t, fg="#b3261e" if erro else "#3b4b5b")
    def set_conf(s, v):
        s.conf = float(v) / 100; s.lim.config(text=f"Confiança mínima: {round(float(v))}%"); s.sujo.set()
    def mudou(s):
        m = s.modo.get()
        s.msg({"hib": "Híbrido: seu modelo (buraco, rachadura, lixo, piso tátil…) + YOLO só para objetos comuns de via (bicicleta, veículos, banco, hidrante…). Pessoas são ignoradas. Triagem visual: confira sempre.",
               "rf": "Só o seu modelo treinado no Roboflow, rodando localmente. Classes sem mapeamento em config.json são ignoradas.",
               "yolo": "Só YOLO pré-treinado: NÃO conhece buracos, rachaduras, lixo nem piso tátil. Serve para comparar com o seu modelo."}[m])
        s.sujo.set()

    # ---------- fontes ----------
    def iniciar(s, tipo, fonte_):
        s.encerrar(); s.parar.clear(); s.sujo.set(); s.ultimo = None; s.pausado = False
        s.thread = threading.Thread(target=s.trabalho, args=(tipo, fonte_), daemon=True); s.thread.start()
    def encerrar(s):
        s.parar.set()
        if s.thread: s.thread.join(timeout=3)
        s.thread = None; s.cam_ativa = False; s.bcam.config(text="Iniciar câmera")
    def abrir(s):
        p = filedialog.askopenfilename(title="Escolher foto ou vídeo", filetypes=[("Imagens e vídeos", "*.jpg *.jpeg *.png *.bmp *.webp *.mp4 *.avi *.mov *.mkv *.webm"), ("Todos", "*.*")])
        if not p: return
        ext = Path(p).suffix.lower()
        if ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
            try: img = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
            except Exception: img = None
            if img is None: return s.msg("Não foi possível abrir a imagem. Use JPG, PNG, BMP ou WebP (HEIC precisa ser convertido) e verifique se o arquivo não está corrompido.", True)
            s.iniciar("foto", img)
        elif ext in (".mp4", ".avi", ".mov", ".mkv", ".webm"):
            cap = cv2.VideoCapture(p)
            if not cap.isOpened(): return s.msg("Não foi possível ler este vídeo. Tente converter para MP4 (H.264).", True)
            s.iniciar("video", cap)
        else: s.msg(f"Formato '{ext or 'desconhecido'}' não suportado. Use JPG, PNG, BMP, WebP, MP4, AVI, MOV, MKV ou WebM.", True)
    def alternar_cam(s):
        if s.cam_ativa: s.encerrar(); s.vis.config(image="", text="Câmera parada."); s.vis.image = None; s.mostrado = None; return
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW) if hasattr(cv2, "CAP_DSHOW") and __import__("sys").platform == "win32" else cv2.VideoCapture(0)
        ok = cap.isOpened() and cap.read()[0]
        if not ok:
            cap.release(); return s.msg("Não foi possível abrir a câmera. Verifique se existe uma câmera, se outro programa a está usando e se o acesso foi permitido (Windows: Configurações > Privacidade > Câmera; macOS: Ajustes > Privacidade > Câmera, para o VS Code/Terminal).", True)
        s.iniciar("camera", cap); s.cam_ativa = True; s.bcam.config(text="Parar câmera"); s.msg("")

    # ---------- thread de análise ----------
    def trabalho(s, tipo, fonte_):
        try:
            if tipo == "foto": frame = fonte_
            while not s.parar.is_set():
                if s.pausado: time.sleep(.05); continue
                if tipo != "foto":
                    ok, frame = fonte_.read()
                    if not ok:
                        if tipo == "video": fonte_.set(cv2.CAP_PROP_POS_FRAMES, 0); continue
                        s.fila.put(("erro", "A câmera parou de enviar imagens.")); break
                elif not s.sujo.is_set(): time.sleep(.05); continue
                s.sujo.clear()
                if (s.modo.get() != "yolo" and s.det.modelo is None) or (s.modo.get() != "rf" and s.det.yolo is None and not s.det.yolo_erro): s.fila.put(("info", "Carregando modelo… (na 1ª vez pode baixar o modelo; precisa de internet)"))
                dets = s.det.detectar(frame, s.conf, s.modo.get())
                with s.trava: s.ultimo = (frame, dets)
                ign = frozenset(s.det.ignoradas)
                if ign and getattr(s, "_alertou", None) != ign:
                    s._alertou = ign; s.fila.put(("info", "Classes ignoradas (sem mapeamento): " + ", ".join(sorted(ign)) + ". Edite mapa_classes_roboflow em models/config.json."))
                if s.det.aviso and getattr(s, "_aviso", None) != s.det.aviso: s._aviso = s.det.aviso; s.fila.put(("info", s.det.aviso))
                s.fila.put(("limpa", None))
        except Exception as e: s.fila.put(("erro", f"Erro: {e}"))
        finally:
            if tipo != "foto": fonte_.release()

    # ---------- interface ----------
    def tick(s):
        try:
            while True:
                k, t = s.fila.get_nowait()
                if k == "erro": s.msg(t, True)
                elif t is not None and k == "info" and t: s.msg(t)
                elif k == "limpa" and s.status.cget("text").startswith("Carregando"): s.mudou()
        except queue.Empty: pass
        with s.trava: u = s.ultimo
        if u is not None and u is not s.mostrado: s.mostrado = u; s.redesenhar()
        s.root.after(30, s.tick)
    def redesenhar(s):
        if not s.mostrado: return
        frame, dets = s.mostrado; lw, lh = max(s.vis.winfo_width(), 200), max(s.vis.winfo_height(), 200)
        h, w = frame.shape[:2]; esc = min(lw / w, lh / h)
        img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).resize((max(1, int(w * esc)), max(1, int(h * esc))))
        txt, g = resumo(dets, s.ocultas, w, h, s.modo.get()); s.res.config(text=txt, fg="#2e7d32" if txt.startswith("Nenhum") else "#b3261e")
        compor(img, dets, s.ocultas, esc, g); s.foto = ImageTk.PhotoImage(img); s.vis.config(image=s.foto, text="")
        s.exib = (esc, (lw - img.width) // 2, (lh - img.height) // 2)
        if time.time() - s.ult_lista > .5: s.ult_lista = time.time(); s.atualiza_lista(dets)
    def atualiza_lista(s, dets):
        v = sorted([d for d in dets if d["cat"] not in s.ocultas], key=lambda d: -d["conf"])
        s.lista.config(state="normal"); s.lista.delete("1.0", "end")
        if not v: s.lista.insert("end", "Nenhum item acima da confiança mínima.")
        for d in v:
            s.lista.insert("end", f"{rotulo(d)} · {round(d['conf'] * 100)}%\n", ("b" + d["cat"],))
            s.lista.tag_config("b" + d["cat"], foreground=CATS[d["cat"]][1], font=("TkDefaultFont", 10, "bold"))
            s.lista.insert("end", CATS[d["cat"]][2] + "\n\n")
        s.lista.config(state="disabled")
    def menu_ctx(s, e):
        s.cat_sob = None
        if s.mostrado:
            esc, ox, oy = s.exib; x, y = (e.x - ox) / esc, (e.y - oy) / esc
            for d in s.mostrado[1]:
                if d["cat"] not in s.ocultas and d["box"][0] <= x <= d["box"][2] and d["box"][1] <= y <= d["box"][3]: s.cat_sob = d["cat"]; break
        s.menu.entryconfig(2, state="normal" if s.cat_sob else "disabled"); s.menu.tk_popup(e.x_root, e.y_root)
    def ocultar(s):
        if s.cat_sob: s.ocultas.add(s.cat_sob); s.redesenhar()
    def pausar(s): s.pausado = not s.pausado; s.msg("Análise pausada." if s.pausado else "")
    def copiar(s):
        if not s.mostrado: return
        t = "\n".join(f"{rotulo(d)} – {round(d['conf'] * 100)}% – {CATS[d['cat']][2]}" for d in s.mostrado[1] if d["cat"] not in s.ocultas)
        s.root.clipboard_clear(); fh, fw = s.mostrado[0].shape[:2]; s.root.clipboard_append(resumo(s.mostrado[1], s.ocultas, fw, fh, s.modo.get())[0] + ("\n" + t if t else "")); s.msg("Lista copiada.")
    def salvar(s):
        if not s.mostrado: return s.msg("Nada para salvar ainda.", True)
        p = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png")], initialfile="triagem-acessibilidade.png")
        if not p: return
        img = Image.fromarray(cv2.cvtColor(s.mostrado[0], cv2.COLOR_BGR2RGB)); fh, fw = s.mostrado[0].shape[:2]; compor(img, s.mostrado[1], s.ocultas, 1.0, resumo(s.mostrado[1], s.ocultas, fw, fh, s.modo.get())[1])
        try: img.save(p); s.msg(f"Imagem salva em {p}")
        except OSError as e: s.msg(f"Não foi possível salvar: {e}", True)
    def fechar(s): s.encerrar(); s.root.destroy()

if __name__ == "__main__":
    root = tk.Tk(); App(root); root.mainloop()
