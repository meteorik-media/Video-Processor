"""Pruebas de Video Processor. Ejecutar desde la raíz del repo:  python -m unittest -v

Las pruebas de integración generan vídeos sintéticos con ffmpeg y se saltan solas si no hay ffmpeg.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import video_processor as vp  # noqa: E402

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


class UnitTests(unittest.TestCase):
    def test_parse_span(self):
        self.assertEqual(vp.parse_span("30m"), 1800)
        self.assertEqual(vp.parse_span("90s"), 90)
        self.assertEqual(vp.parse_span("1h"), 3600)
        self.assertEqual(vp.parse_span("1800"), 1800)
        self.assertEqual(vp.parse_span("0"), 0)
        self.assertEqual(vp.parse_span(None), 0)
        with self.assertRaises(ValueError):
            vp.parse_span("abc")

    def test_parse_rate(self):
        self.assertAlmostEqual(vp.parse_rate("30000/1001"), 29.97, places=2)
        self.assertEqual(vp.parse_rate("0/0"), 0)
        self.assertEqual(vp.parse_rate(None), 0)

    def test_target_size_horizontal_vertical_and_no_upscale(self):
        self.assertEqual(vp.target_size(1920, 1080, 360), (640, 360))
        self.assertEqual(vp.target_size(1920, 1080, 480), (854, 480))
        self.assertEqual(vp.target_size(1080, 1920, 360), (360, 640))
        self.assertEqual(vp.target_size(320, 240, 360), (320, 240))

    def test_plan_chunks(self):
        self.assertEqual(vp.plan_chunks(100, 0), [(0.0, None)])
        self.assertEqual(vp.plan_chunks(100, 200), [(0.0, None)])
        self.assertEqual(vp.plan_chunks(20, 8), [(0, 8), (8, 8), (16, None)])
        # un resto diminuto (<10%) se une al trozo anterior
        self.assertEqual(vp.plan_chunks(16.4, 8), [(0, 8), (8, None)])

    def test_esc_filter_path_windows(self):
        self.assertEqual(vp.esc_filter_path(r"C:\Windows\Fonts\arial.ttf"), "C\\:/Windows/Fonts/arial.ttf")

    def test_build_vf(self):
        info = {"width": 1920, "height": 1080, "fps": 60.0, "duration": 10}
        s = {"height": 360, "fps": 2, "timecode": True}
        vf = vp.build_vf(info, s, 1800, "/f/font.ttf")
        self.assertTrue(vf.startswith("fps=2,scale=640:360"))
        self.assertIn("%{pts\\:hms\\:1800.000}", vf)
        self.assertEqual(vp.build_vf({"width": 640, "height": 360, "fps": 2.0, "duration": 1},
                                     {"height": 360, "fps": 2, "timecode": False}, 0, None), "null")

    def test_build_cli_args_from_web_form(self):
        mode, argv, out = vp.build_cli_args({
            "mode": "dry", "inputs": ["/raw"], "output": "/out", "preset": "ai-log", "chunk": "30m",
            "scenes": 0.3, "height": "", "audio": False, "timecode": None, "force": True, "interval": 60})
        self.assertEqual((mode, out), ("run", "/out"))
        self.assertEqual(argv, ["run", "/raw", "-o", "/out", "--preset", "ai-log", "--scenes", "0.3",
                                "--chunk", "30m", "--no-audio", "--force", "--dry-run"])
        with self.assertRaises(ValueError):
            vp.build_cli_args({"mode": "run", "inputs": [], "output": "/out"})
        with self.assertRaises(ValueError):
            vp.build_cli_args({"mode": "run", "inputs": ["x"], "output": "/o", "chunk": "zz"})
        with self.assertRaises(ValueError):
            vp.build_cli_args({"mode": "run", "inputs": ["x"], "output": "/o", "fps": "--evil"})

    def test_presets_have_ai_log_recipe(self):
        p = vp.BUILTIN_PRESETS["ai-log"]
        self.assertEqual((p["height"], p["fps"], p["crf"], p["audio"]), (360, 2, 34, False))


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe no disponibles")
class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="vp-test-"))
        cls.inp = cls.tmp / "in"
        (cls.inp / "sub").mkdir(parents=True)
        run = lambda *a: subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *a], check=True)  # noqa: E731
        run("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i", "sine=frequency=440",
            "-t", "10", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(cls.inp / "cards_0001.mp4"))
        run("-f", "lavfi", "-i", "color=c=red:s=640x360:d=4:r=30", "-f", "lavfi", "-i", "color=c=blue:s=640x360:d=4:r=30",
            "-filter_complex", "[0][1]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p", str(cls.inp / "sub" / "cards_0002.mp4"))
        (cls.inp / "rota.mp4").write_text("no es un vídeo")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_tool(self, out, *extra):
        return vp.main(["run", str(self.inp), "-o", str(out), *extra])

    def probe_out(self, path):
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "stream=codec_type,width,height,avg_frame_rate", "-of", "json", str(path)],
                           capture_output=True, text=True, check=True)
        return json.loads(r.stdout)["streams"]

    def test_ai_log_recipe_chunks_markers_and_idempotence(self):
        out = self.tmp / "out"
        rc = self.run_tool(out, "--chunk", "4s", "--scenes", "0.3")
        self.assertEqual(rc, 1)  # rota.mp4 falla, el resto sigue
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["entries"]["rota.mp4|ai-log"]["status"], "failed")
        e = manifest["entries"]["cards_0001.mp4|ai-log"]
        self.assertEqual([(o["start"], o["end"]) for o in e["outputs"]], [(0.0, 4.0), (4.0, 8.0), (8.0, 10.0)])
        for o in e["outputs"]:
            streams = self.probe_out(out / o["file"])
            self.assertEqual([s["codec_type"] for s in streams], ["video"])  # sin audio
            self.assertEqual((streams[0]["width"], streams[0]["height"], streams[0]["avg_frame_rate"]),
                             (640, 360, "2/1"))
        self.assertEqual([o["file"] for o in manifest["entries"]["sub/cards_0002.mp4|ai-log"]["outputs"]],
                         ["sub/cards_0002.ai-log.part01.mp4", "sub/cards_0002.ai-log.part02.mp4"])
        times = [t for t, _ in manifest["entries"]["sub/cards_0002.mp4|ai-log"]["markers"]]
        self.assertEqual(times, [4.0])
        self.assertTrue((out / "markers.csv").is_file())
        self.assertEqual((out / "log_raw.csv").read_text(encoding="utf-8").strip().split(",")[0], "archivo")
        # segunda pasada: nada que procesar salvo el archivo roto
        before = (out / "cards_0001.ai-log.part01.mp4").stat().st_mtime_ns
        self.run_tool(out, "--chunk", "4s", "--scenes", "0.3")
        self.assertEqual((out / "cards_0001.ai-log.part01.mp4").stat().st_mtime_ns, before)

    def test_phone_video_with_rotation_metadata_is_not_distorted(self):
        phone = self.tmp / "phone"
        phone.mkdir()
        # 1280x720 almacenado + rotación de 90° = vídeo vertical 720x1280 al reproducirse
        subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-display_rotation", "90", "-i",
                        str(self.inp / "cards_0001.mp4"), "-c", "copy", "-an", str(phone / "movil_0001.mp4")],
                       check=True)
        self.assertEqual((vp.probe(phone / "movil_0001.mp4")["width"], vp.probe(phone / "movil_0001.mp4")["height"]),
                         (720, 1280))
        out = self.tmp / "out-phone"
        self.assertEqual(vp.main(["run", str(phone), "-o", str(out)]), 0)
        s = self.probe_out(out / "movil_0001.ai-log.mp4")[0]
        self.assertEqual((s["width"], s["height"]), (360, 640))

    def test_human_proxy_keeps_audio_and_originals_untouched(self):
        out = self.tmp / "out-human"
        src = self.inp / "cards_0001.mp4"
        before = (src.stat().st_size, src.stat().st_mtime_ns)
        vp.main(["run", str(src), "-o", str(out), "--preset", "human-proxy"])
        streams = self.probe_out(out / "cards_0001.human-proxy.mp4")
        self.assertEqual(sorted(s["codec_type"] for s in streams), ["audio", "video"])
        self.assertEqual((src.stat().st_size, src.stat().st_mtime_ns), before)


class WebTests(unittest.TestCase):
    """Servidor local: token y host obligatorios, y un trabajo completo de punta a punta."""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer
        cls.token = "tok123"
        cls.job = vp.JobRunner()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), lambda *a, **k: None)
        cls.port = cls.server.server_address[1]
        cls.server.RequestHandlerClass = vp.make_handler(cls.job, None, cls.token, cls.port)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, path, body=None, token="tok123", host=None):
        import urllib.error
        import urllib.request
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}",
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"X-VP-Token": token, "Content-Type": "application/json",
                                              **({"Host": host} if host else {})})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def test_rejects_wrong_token_and_foreign_host(self):
        self.assertEqual(self.call("/api/state", token="nope")[0], 403)
        self.assertEqual(self.call("/api/state", host="evil.example")[0], 403)
        code, data = self.call("/api/state")
        self.assertEqual(code, 200)
        self.assertIn("ai-log", data["presets"])

    def test_browse_lists_folders_and_videos(self):
        d = Path(tempfile.mkdtemp(prefix="vp-browse-"))
        self.addCleanup(shutil.rmtree, d, True)
        (d / "sub").mkdir()
        (d / "a.mp4").write_bytes(b"x")
        (d / "notes.txt").write_text("x")
        import urllib.parse
        code, data = self.call("/api/browse?path=" + urllib.parse.quote(str(d)))
        self.assertEqual((code, data["dirs"], [v["name"] for v in data["videos"]]), (200, ["sub"], ["a.mp4"]))

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe no disponibles")
    def test_job_runs_end_to_end(self):
        import time as _t
        import urllib.parse
        d = Path(tempfile.mkdtemp(prefix="vp-web-"))
        self.addCleanup(shutil.rmtree, d, True)
        subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=size=640x360:rate=30", "-t", "3", "-pix_fmt", "yuv420p", str(d / "c_0001.mp4")], check=True)
        code, _ = self.call("/api/start", {"mode": "run", "inputs": [str(d / "c_0001.mp4")], "output": str(d / "out")})
        self.assertEqual(code, 200)
        for _ in range(100):
            _, snap = self.call("/api/job?since=0")
            if snap["state"] != "running":
                break
            _t.sleep(0.2)
        self.assertEqual(snap["state"], "done")
        _, res = self.call("/api/results?output=" + urllib.parse.quote(str(d / "out")))
        self.assertEqual([i["status"] for i in res["items"]], ["ok"])


if __name__ == "__main__":
    unittest.main()
