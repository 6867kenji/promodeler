"""Local, single-user character makeup preview for the canonical base."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import secrets
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import canonical


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "character" / "bases" / "RiggedWoman_v6" / "manifest.json"
STARTER = ROOT / "character" / "canonical_recipes" / "streetwear-woman.json"
PAGE = Path(__file__).with_name("makeup.html")
LIVE_JS = Path(__file__).with_name("makeup_live.js")
VENDOR = Path(__file__).with_name("vendor")
SLIDER_LABELS = {
    "face.faceRoundness": "顔の丸み", "face.jawWidth": "あご幅",
    "face.eyeSize": "目の大きさ", "face.noseSize": "鼻の大きさ",
    "face.cheekVolume": "頬のふくらみ", "body.shoulderWidth": "肩幅",
    "body.chest": "胸の形（0＝平ら、0.5＝元の形）", "body.armLength": "腕の長さ",
    "body.legLength": "脚の長さ",
}
MODULE_LABELS = {
    "hair_blue_silver_long": "青銀のロング", "hair_headband_black": "黒髪・ヘッドバンド",
    "hair_ponytail_brown": "茶色のポニーテール", "hair_ponytail_telo": "茶色のポニーテール＋後れ毛",
    "sports_bra": "スポーツブラ", "blouse_a": "ブラウス", "female_tank_top": "タンクトップ",
    "amber_crop_tshirt": "短丈 T シャツ", "streetwear_sport_shirt": "スポーツシャツ",
    "medieval_thin": "薄手のドレス", "medieval_thick": "厚手のドレス",
    "lingerie_set": "ランジェリーセット", "female_outfit": "女性用セット",
    "megane_uniform": "制服", "female_cargo_pants": "カーゴパンツ",
    "amber_jeans": "ジーンズ", "streetwear_formal_pants": "フォーマルパンツ",
    "female_jacket": "ジャケット", "amber_leather_jacket": "革ジャケット",
    "streetwear_bomber_jacket": "ボンバージャケット",
    "amber_boots": "ブーツ", "streetwear_shoes": "スニーカー",
    "streetwear_bag": "バッグ",
}


class MakeupState:
    def __init__(self, out: Path):
        self.out = out.resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.manifest, _ = canonical.load_manifest(MANIFEST)
        self.starter = json.loads(STARTER.read_text(encoding="utf-8"))
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.Lock()
        self.phase = "starting"
        self.message = "基準モデルを準備しています"
        self.baseline = None
        self.current = None
        self.last_recipe = None
        self.worker = None
        self.live_phase = "starting"
        self.live_message = "3Dプレビューを準備しています"
        self.live_url = None

    def _live_signature(self) -> str:
        model = Path(self.manifest["model"])
        script = Path(__file__).with_name("makeup_live_export.py")
        payload = json.dumps({"model": str(model), "size": model.stat().st_size,
                              "modified": model.stat().st_mtime_ns,
                              "manifest": self.manifest}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8") + script.read_bytes()).hexdigest()[:16]

    def _prepare_live(self) -> None:
        try:
            folder = self.out / "live"
            folder.mkdir(exist_ok=True)
            model = folder / "model.glb"
            signature = self._live_signature()
            marker = folder / "version.txt"
            if not model.is_file() or not marker.is_file() or marker.read_text(encoding="utf-8") != signature:
                command = [canonical.find_blender(), "-b", "--factory-startup", "--disable-autoexec",
                           "--python-exit-code", "23", "--python",
                           str(Path(__file__).with_name("makeup_live_export.py")), "--",
                           self.manifest["model"], str(MANIFEST), str(model)]
                with (folder / "export.log").open("w", encoding="utf-8") as log:
                    done = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                          cwd=ROOT, check=False)
                if done.returncode or not model.is_file():
                    raise RuntimeError("3Dプレビューの準備に失敗しました。live/export.log を確認してください")
                marker.write_text(signature, encoding="utf-8")
            with self.lock:
                self.live_url = self._url(model) + "?v=" + signature
                self.live_phase = "ready"
                self.live_message = "3Dプレビューを操作できます"
        except Exception as exc:
            with self.lock:
                self.live_phase = "error"
                self.live_message = str(exc)

    def begin_live(self) -> None:
        threading.Thread(target=self._prepare_live, daemon=True).start()

    def _url(self, path: Path) -> str:
        return "/files/" + path.resolve().relative_to(self.out).as_posix()

    def _result(self, directory: Path) -> dict:
        model = directory / "model.glb"
        preview = directory / "preview.png"
        face = directory / "face.png"
        if not model.is_file() or not preview.is_file():
            raise RuntimeError("Blender の出力ファイルが見つかりません")
        if not face.is_file():
            command = [canonical.find_blender(), "-b", "--factory-startup", "--disable-autoexec",
                       "--python-exit-code", "23", "--python",
                       str(Path(__file__).with_name("makeup_face_render.py")), "--",
                       str(model), str(face)]
            with (directory / "face-render.log").open("w", encoding="utf-8") as log:
                done = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT, check=False)
            if done.returncode or not face.is_file():
                raise RuntimeError("顔の拡大画像を作成できませんでした。face-render.log を確認してください")
        return {"full": self._url(preview), "face": self._url(face),
                "glb": self._url(model), "recipe": self._url(directory / "recipe.json")}

    def _build(self, recipe: dict, baseline: bool) -> None:
        try:
            directory, report = canonical.build(recipe, MANIFEST, self.out / "build" / "canonical",
                                                render=True, strict=True)
            if report.get("status") != "ok":
                raise RuntimeError(report.get("error", {}).get("message", "Blender で生成できませんでした"))
            result = self._result(directory)
            with self.lock:
                if baseline:
                    self.baseline = result
                    self.current = result
                    self.last_recipe = recipe
                else:
                    self.current = result
                    self.last_recipe = recipe
                self.phase = "ready"
                self.message = "プレビューができました"
        except Exception as exc:
            with self.lock:
                self.phase = "error"
                self.message = str(exc)

    def begin_baseline(self) -> None:
        self.worker = threading.Thread(target=self._build, args=(self.starter, True), daemon=True)
        self.worker.start()

    def make_recipe(self, settings: dict) -> dict:
        if not isinstance(settings, dict) or not {"sliders", "modules", "bag"} <= set(settings) or set(settings) - {"sliders", "modules", "bag", "underwear"}:
            raise ValueError("操作内容を読み取れません")
        sliders, modules = settings["sliders"], settings["modules"]
        if not isinstance(sliders, dict) or set(sliders) != set(self.manifest["parameters"]):
            raise ValueError("スライダーの項目が正しくありません")
        if not isinstance(modules, dict) or set(modules) != {"hairStyle", *canonical.WARDROBE}:
            raise ValueError("髪型または衣装の項目が正しくありません")
        if type(settings["bag"]) is not bool:
            raise ValueError("バッグの指定が正しくありません")
        underwear = settings.get("underwear", {"top": True, "bottom": True})
        if (not isinstance(underwear, dict) or set(underwear) != {"top", "bottom"}
                or any(type(value) is not bool for value in underwear.values())):
            raise ValueError("下着の指定が正しくありません")
        recipe = copy.deepcopy(self.starter)
        recipe["id"] = "makeup-preview"
        recipe["name"] = "Makeup Preview"
        recipe["face"] = {}
        recipe["body"] = {}
        for path, value in sliders.items():
            if type(value) not in (int, float) or not 0 <= value <= 1:
                raise ValueError(f"{path} は 0～1 の値にしてください")
            group, key = path.split(".", 1)
            if path == "body.chest" and value > 0.5:
                raise ValueError("胸の形は 0～0.5 の範囲で調整してください")
            recipe[group][key] = float(value)
        for key, value in modules.items():
            mapping = self.manifest["modules"].get("appearance.hairStyle" if key == "hairStyle" else f"wardrobe.{key}", {})
            if value is not None and value not in mapping:
                raise ValueError(f"{key} の候補が見つかりません")
        if modules["hairStyle"] is None:
            raise ValueError("髪型を選んでください")
        if modules["dress"] is not None and any(modules[key] is not None for key in ("top", "bottom", "outer")):
            raise ValueError("ドレスと上下の衣装は同時に選べません")
        recipe["appearance"] = {"hairStyle": modules["hairStyle"]}
        recipe["wardrobe"] = {key: value for key, value in modules.items() if key != "hairStyle" and value is not None}
        recipe["accessories"] = ["streetwear_bag"] if settings["bag"] else []
        recipe["underwear"] = underwear.copy()
        canonical.validate(recipe)
        missing = canonical.compatibility(recipe, self.manifest)
        if missing:
            raise ValueError("対応していない設定: " + ", ".join(missing))
        return recipe

    def start_build(self, settings: dict) -> None:
        recipe = self.make_recipe(settings)
        with self.lock:
            if self.phase == "building" or self.baseline is None:
                raise RuntimeError("現在の生成が完了するまでお待ちください")
            self.phase = "building"
            self.message = "変更したモデルを生成しています"
            self.worker = threading.Thread(target=self._build, args=(recipe, False), daemon=True)
            self.worker.start()

    def save(self, name: str, settings: dict | None = None) -> dict:
        if not isinstance(name, str) or len(name) > 80:
            raise ValueError("名前は 80 文字以内にしてください")
        slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")
        if not slug:
            raise ValueError("保存名には半角英数字を含めてください")
        if settings is not None:
            recipe = self.make_recipe(settings)
        else:
            with self.lock:
                if self.last_recipe is None:
                    raise RuntimeError("設定を読み取れません")
                recipe = copy.deepcopy(self.last_recipe)
        recipe["id"] = slug
        recipe["name"] = name.strip()
        folder = self.out / "recipes"
        folder.mkdir(exist_ok=True)
        path = folder / f"{slug}.json"
        try:
            with path.open("x", encoding="utf-8") as target:
                target.write(json.dumps(recipe, ensure_ascii=False, indent=2) + "\n")
        except FileExistsError:
            raise ValueError("同じ保存名のレシピがあります。別の名前にしてください")
        with self.lock:
            self.last_recipe = recipe
        return {"path": str(path), "url": self._url(path)}

    def snapshot(self) -> dict:
        with self.lock:
            return {"phase": self.phase, "message": self.message,
                    "baseline": self.baseline, "current": self.current,
                    "recipe": self.last_recipe, "livePhase": self.live_phase,
                    "liveMessage": self.live_message, "liveModel": self.live_url}


def serve(out: str | Path, port: int = 8765) -> None:
    state = MakeupState(Path(out))

    class Handler(BaseHTTPRequestHandler):
        def _json(self, value: dict, status: int = 200) -> None:
            data = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _file(self, path: Path, kind: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(path.stat().st_size))
            reusable = path.suffix.lower() == ".glb" or path.is_relative_to(VENDOR)
            self.send_header("Cache-Control", "private, max-age=3600" if reusable else "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    self.wfile.write(chunk)

        def do_GET(self) -> None:
            route = urlparse(self.path).path
            if route == "/":
                return self._file(PAGE, "text/html; charset=utf-8")
            if route == "/makeup_live.js":
                return self._file(LIVE_JS, "text/javascript; charset=utf-8")
            if route.startswith("/vendor/"):
                path = (VENDOR / unquote(route[len("/vendor/"):])).resolve()
                if not path.is_relative_to(VENDOR) or not path.is_file() or path.suffix != ".js":
                    return self._json({"error": "表示できないファイルです"}, 404)
                return self._file(path, "text/javascript; charset=utf-8")
            if route == "/api/config":
                return self._json({"token": state.token, "starter": state.starter,
                                   "parameters": {key: {"label": SLIDER_LABELS.get(key, key),
                                                        "max": 0.5 if key == "body.chest" else 1}
                                                  for key in state.manifest["parameters"]},
                                   "modules": {key: [{"id": item, "label": MODULE_LABELS.get(item, item)}
                                                     for item in choices]
                                               for key, choices in state.manifest["modules"].items()},
                                   "parameterSpecs": state.manifest["parameters"],
                                   "moduleObjects": state.manifest["modules"],
                                   "bodyMasks": state.manifest.get("bodyMasks", {}),
                                   "bodyMeshMasks": state.manifest.get("bodyMeshMasks", {}),
                                   "accessories": state.manifest.get("accessories", {})})
            if route == "/api/status":
                return self._json(state.snapshot())
            if route.startswith("/files/"):
                relative = unquote(route[len("/files/"):])
                path = (state.out / relative).resolve()
                if not path.is_relative_to(state.out) or not path.is_file():
                    return self._json({"error": "ファイルが見つかりません"}, 404)
                kinds = {".png": "image/png", ".glb": "model/gltf-binary",
                         ".json": "application/json; charset=utf-8"}
                if path.suffix.lower() not in kinds:
                    return self._json({"error": "表示できない形式です"}, 403)
                return self._file(path, kinds[path.suffix.lower()])
            self._json({"error": "ページが見つかりません"}, 404)

        def do_POST(self) -> None:
            route = urlparse(self.path).path
            if route not in ("/api/build", "/api/save"):
                return self._json({"error": "操作が見つかりません"}, 404)
            if self.headers.get("X-Makeup-Token") != state.token:
                return self._json({"error": "画面を再読み込みしてください"}, 403)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 32768:
                    raise ValueError("送信内容が大きすぎます")
                payload = json.loads(self.rfile.read(length))
                if route == "/api/build":
                    state.start_build(payload)
                    return self._json({"phase": "building"}, 202)
                if not isinstance(payload, dict):
                    raise ValueError("保存名を読み取れません")
                return self._json(state.save(payload.get("name"), payload.get("settings")))
            except (ValueError, RuntimeError, KeyError, TypeError) as exc:
                return self._json({"error": str(exc)}, 400)

        def log_message(self, format: str, *args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    state.begin_live()
    state.begin_baseline()
    print(f"Character makeup: http://127.0.0.1:{server.server_port}/", flush=True)
    print(f"Output: {state.out}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
