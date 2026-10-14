import { useEffect, useRef, useState } from "react";
import {
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Container,
  FormControlLabel,
  LinearProgress,
  MenuItem,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { api, download, json } from "./api";
import type { Cue, Hardware, Media, Result, Task } from "./types";

const stages: Record<string, string> = {
  loading_model: "加载或下载所选模型",
  extracting_audio: "提取音频",
  transcribing: "语音识别",
  generating_subtitles: "生成字幕",
  exporting: "烧录字幕并编码视频",
  muxing: "封装字幕（视频、音频不转码）",
  cancelling: "正在取消导出……",
  finalizing: "编码已结束，正在验证导出文件",
  cancel_wait_model: "正在取消处理：等待模型下载/加载安全返回……",
  cancel_wait_inference: "正在取消处理：等待当前推理步骤返回……",
  cancel_ffmpeg: "正在取消处理：停止音频提取并清理……",
  cancel_subtitles: "正在取消处理：停止字幕生成并清理……",
};
const presets: Record<string, string> = {
  fast: "small",
  balanced: "large-v3-turbo",
  quality: "large-v3",
};
function plain(cues: Cue[]) {
  const paragraphs: string[] = [];
  let group = -1;
  cues.forEach((c) => {
    const text = c.text.replace(/\s+/g, " ").trim();
    if (c.group !== group) {
      paragraphs.push(text);
    } else {
      const last = paragraphs.length - 1;
      paragraphs[last] += c.join_before !== undefined && c.join_before !== null ? c.join_before + text :
        (/[A-Za-z0-9.,!?]$/.test(paragraphs[last]) && /^[A-Za-z0-9]/.test(text)
          ? " "
          : "") + text;
    }
    group = c.group;
  });
  return paragraphs.join("\n");
}
function clock(n: number) {
  return `${Math.floor(n / 60)
    .toString()
    .padStart(2, "0")}:${(n % 60).toFixed(2).padStart(5, "0")}`;
}

function mergeVideoTask(current: Task | null, incoming: Task) {
  if (!current || current.id !== incoming.id) return incoming;
  if (["completed", "failed", "cancelled"].includes(current.status)) return current;
  if (current.status === "cancelling" && ["pending", "processing"].includes(incoming.status)) return current;
  if (current.status === "processing" && incoming.status === "pending") return current;
  return incoming;
}

export default function App() {
  const [hw, setHw] = useState<Hardware | null>(null),
    [media, setMedia] = useState<Media | null>(null);
  const [task, setTask] = useState<Task | null>(null),
    [videoTask, setVideoTask] = useState<Task | null>(null),
    [result, setResult] = useState<Result | null>(null);
  const [resultTaskId, setResultTaskId] = useState<string | null>(null);
  const activeTaskId = useRef<string | null>(null);
  const loadedResultId = useRef<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const uploadController = useRef<AbortController | null>(null);
  const [starting, setStarting] = useState(false);
  const startCancelled = useRef(false);
  const [processCancelBusy, setProcessCancelBusy] = useState(false);
  const processCancelSubmitting = useRef(false);
  const [cues, setCues] = useState<Cue[]>([]),
    [dirty, setDirty] = useState(false),
    [tab, setTab] = useState(0),
    [time, setTime] = useState(0);
  const [quality, setQuality] = useState("balanced"),
    [language, setLanguage] = useState("auto"),
    [device, setDevice] = useState("auto"),
    [model, setModel] = useState("large-v3-turbo"),
    [compute, setCompute] = useState("auto");
  const [beam, setBeam] = useState(5),
    [vad, setVad] = useState(true),
    [words, setWords] = useState(true),
    [allowDownload, setAllowDownload] = useState(false),
    [encoder, setEncoder] = useState("libx264");
  const [exportMode, setExportMode] = useState<"burn" | "mux">("burn");
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState("");
  const player = useRef<HTMLVideoElement | null>(null);
  const [cancelBusy, setCancelBusy] = useState(false);
  const cancelSubmitting = useRef(false);
  const running = (t: Task | null) =>
    !!t && ["pending", "processing", "cancelling"].includes(t.status);
  const locked = busy || running(task) || running(videoTask);
  const loadCompletedResult = async (t: Task, disposed: () => boolean = () => false) => {
    if (t.status !== "completed" || loadedResultId.current === t.id) return;
    const r = await api<Result>(`/tasks/${t.id}/result`);
    if (disposed() || activeTaskId.current !== t.id || loadedResultId.current === t.id) return;
    loadedResultId.current = t.id;
    setResult(r);
    setResultTaskId(t.id);
    setCues(r.cues);
    setDirty(false);
  };
  useEffect(() => {
    api<Hardware>("/system/info")
      .then((h) => {
        setHw(h);
        if (h.encoders.includes("h264_nvenc")) setEncoder("h264_nvenc");
      })
      .catch((e) => setError(String(e)));
  }, []);
  useEffect(() => {
    if (!running(task) || !task) return;
    let disposed = false;
    const poll = async () => {
      try {
        const t = await api<Task>(`/tasks/${task.id}`);
        if (disposed) return;
        if (t.status === "completed") {
          await loadCompletedResult(t, () => disposed);
          if (disposed) return;
        }
        if (t.status === "failed") setError(t.error || "识别失败");
        setTask((current) => current?.id === t.id ? mergeVideoTask(current, t) : current);
      } catch (e) {
        if (!disposed) setError(String(e));
      }
    };
    const id = setInterval(() => void poll(), 1500);
    return () => {
      disposed = true;
      clearInterval(id);
    };
  }, [task?.id, task?.status]);
  useEffect(() => {
    if (!running(videoTask) || !videoTask) return;
    let disposed = false;
    const id = setInterval(() => {
      api<Task>(`/tasks/${videoTask.id}`)
        .then((t) => {
          if (disposed) return;
          setVideoTask((current) => current?.id === t.id ? mergeVideoTask(current, t) : current);
          if (t.status === "failed") setError(t.error || "导出失败");
        })
        .catch((e) => {
          if (!disposed) setError(String(e));
        });
    }, 1500);
    return () => {
      disposed = true;
      clearInterval(id);
    };
  }, [videoTask?.id, videoTask?.status]);
  const cancelExport = async () => {
    if (!videoTask || cancelSubmitting.current) return;
    cancelSubmitting.current = true;
    setCancelBusy(true);
    setError("");
    try {
      const cancelled = await api<Task>(`/tasks/${videoTask.id}/cancel`, { method: "POST" });
      setVideoTask((current) => mergeVideoTask(current, cancelled));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      cancelSubmitting.current = false;
      setCancelBusy(false);
    }
  };
  const cancelProcessing = async () => {
    if (processCancelSubmitting.current) return;
    if (starting) {
      startCancelled.current = true;
      setProcessCancelBusy(true);
      return;
    }
    if (!task || !running(task) || task.status === "cancelling") return;
    processCancelSubmitting.current = true;
    setProcessCancelBusy(true);
    try {
      const cancelled = await api<Task>(`/tasks/${task.id}/cancel`, { method: "POST" });
      await loadCompletedResult(cancelled);
      setTask((current) => current?.id === cancelled.id ? mergeVideoTask(current, cancelled) : current);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      processCancelSubmitting.current = false;
      setProcessCancelBusy(false);
    }
  };
  const execute = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const upload = (file: File) =>
    execute(async () => {
      const controller = new AbortController();
      uploadController.current = controller;
      setUploading(true);
      try {
      const m = await api<Media>(`/media/upload?filename=${encodeURIComponent(file.name)}`, {
        method: "POST", body: file, signal: controller.signal,
        headers: { "Content-Type": "application/octet-stream" },
      });
      if (controller.signal.aborted) return;
      setMedia(m);
      setTask(null);
      activeTaskId.current = null;
      loadedResultId.current = null;
      setVideoTask(null);
      setResult(null);
      setResultTaskId(null);
      setCues([]);
      setDirty(false);
      setTime(0);
      } catch (e) {
        if (controller.signal.aborted) setNotice("上传已中止；服务器将清理不完整文件。");
        else throw e;
      } finally {
        uploadController.current = null;
        setUploading(false);
      }
    });
  const save = async () => {
    if (!resultTaskId || !dirty) return;
    const r = await api<Result>(
      `/tasks/${resultTaskId}/subtitles`,
      json({ cues }, "PUT"),
    );
    setCues(r.cues);
    setResult(r);
    setDirty(false);
  };
  const text = plain(cues),
    active = cues.find((c) => time >= c.start && time < c.end);
  const activeDevice = device === "auto" ? (hw?.cuda ? "cuda" : hw?.metal ? "metal" : "cpu") : device;
  const supported = hw?.compute_types[activeDevice as "cpu" | "cuda" | "metal"] || [];
  const edit = (id: number, key: "text" | "start" | "end", value: string) => {
    setCues((old) =>
      old.map((c) =>
        c.id === id
          ? { ...c, [key]: key === "text" ? value : Number(value) }
          : c,
      ),
    );
    setDirty(true);
    setVideoTask(null);
  };
  const base = media?.name.replace(/\.[^.]+$/, "") || "media";
  return (
    <Container maxWidth="lg" sx={{ py: 3 }}>
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        mb={3}
      >
        <Box>
          <Typography variant="h4" fontWeight={650}>
            Media Tool
          </Typography>
          <Typography color="text.secondary">本地 AI 字幕与语音转写</Typography>
        </Box>
        <Chip label="本地处理 · 无云端 AI" variant="outlined" />
      </Stack>
      {error && (
        <Alert severity="error" onClose={() => setError("")} sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      {notice && (
        <Alert severity="success" sx={{ mb: 2 }}>
          {notice}
        </Alert>
      )}
      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Typography variant="body2">
          {hw
            ? `${hw.apple_silicon ? hw.inference_note : `${hw.gpu.map((g) => `${g.name} · ${(g.memory_mb / 1024).toFixed(1)} GB`).join(" / ") || "未检测到 NVIDIA GPU"} ｜ CTranslate2 CUDA：${hw.cuda ? "可探测（推理待验证）" : "不可用，支持 CPU"}`} ｜ FFmpeg：${hw.ffmpeg ? "可用" : "缺失"} ｜ FFprobe：${hw.ffprobe ? "可用" : "缺失"}`
            : "正在检测环境…"}
        </Typography>
        {hw?.warnings.map((w) => (
          <Typography key={w} color="warning.main" variant="body2">
            {w}
          </Typography>
        ))}
      </Paper>
      <Paper variant="outlined" sx={{ p: 3, mb: 2 }}>
        <Box
          className="dropzone"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const file = e.dataTransfer.files[0];
            if (file && !locked) void upload(file);
          }}
        >
          <Typography mb={1}>拖入视频或音频文件</Typography>
          <Button component="label" variant="outlined" disabled={locked}>
            选择文件
            <input
              hidden
              type="file"
              accept=".mp4,.mkv,.mov,.mp3,.wav,.m4a"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void upload(file);
                e.target.value = "";
              }}
            />
          </Button>
          <Typography
            variant="caption"
            display="block"
            mt={1}
            color="text.secondary"
          >
            MP4 · MKV · MOV · MP3 · WAV · M4A
          </Typography>
        </Box>
        {media && (
          <Stack direction="row" spacing={2} my={2}>
            <Typography fontWeight={600}>{media.name}</Typography>
            <Typography color="text.secondary">
              {clock(media.duration)} · {(media.size / 1024 / 1024).toFixed(1)}{" "}
              MB {media.video ? `· ${media.width} × ${media.height}` : ""}
            </Typography>
          </Stack>
        )}
        {media?.hdr && (
          <Alert severity="warning" sx={{ my: 2 }}>
            HDR 输入可识别和导出文本，当前不支持烧录 HDR 视频。
          </Alert>
        )}
        <Stack direction="row" spacing={2} my={2}>
          <TextField
            select
            label="识别质量"
            value={quality}
            disabled={locked}
            onChange={(e) => {
              setQuality(e.target.value);
              setModel(presets[e.target.value]);
              setCompute("auto");
            }}
            fullWidth
          >
            <MenuItem value="fast">快速 · small / int8</MenuItem>
            <MenuItem value="balanced">均衡 · turbo / int8_float16</MenuItem>
            <MenuItem value="quality">高质量 · large-v3 / float16</MenuItem>
          </TextField>
          <TextField
            select
            label="语言"
            value={language}
            disabled={locked}
            onChange={(e) => setLanguage(e.target.value)}
            fullWidth
          >
            {[
              ["auto", "自动检测"],
              ["zh", "中文"],
              ["ja", "日语"],
              ["en", "英语"],
            ].map(([v, l]) => (
              <MenuItem value={v} key={v}>
                {l}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="运算设备"
            value={device}
            disabled={locked}
            onChange={(e) => {
              setDevice(e.target.value);
              setCompute("auto");
            }}
            fullWidth
          >
            <MenuItem value="auto">自动</MenuItem>
            <MenuItem value="cuda" disabled={!hw?.cuda}>
              CUDA
            </MenuItem>
            <MenuItem value="metal" disabled={!hw?.metal}>Metal GPU（Apple Silicon）</MenuItem>
            <MenuItem value="cpu">CPU</MenuItem>
          </TextField>
        </Stack>
        <Accordion elevation={0} disableGutters>
          <AccordionSummary>高级设置 ▾</AccordionSummary>
          <AccordionDetails>
            <Box
              sx={{
                display: "grid",
                gridTemplateColumns:
                  "repeat(auto-fit, minmax(min(100%, 160px), 1fr))",
                gap: 2,
              }}
            >
              <TextField
                select
                label="模型"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                disabled={locked}
                fullWidth
              >
                {["small", "medium", "large-v3-turbo", "large-v3"].map((v) => (
                  <MenuItem key={v} value={v}>
                    {v}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="计算精度"
                value={compute}
                onChange={(e) => setCompute(e.target.value)}
                disabled={locked}
                fullWidth
              >
                {[
                  "auto",
                  ...["float16", "int8_float16", "int8", "float32"].filter((v) =>
                    supported.includes(v),
                  ),
                ].map((v) => (
                  <MenuItem key={v} value={v}>
                    {v}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                label="Beam Size"
                type="number"
                value={activeDevice === "metal" ? 1 : beam}
                onChange={(e) => setBeam(Number(e.target.value))}
                disabled={locked || activeDevice === "metal"}
                helperText={activeDevice === "metal" ? "MLX 使用贪心解码" : undefined}
                slotProps={{ htmlInput: { min: 1, max: 10 } }}
                fullWidth
              />
            </Box>
            <FormControlLabel
              control={
                <Checkbox
                  checked={vad}
                  onChange={(e) => setVad(e.target.checked)}
                  disabled={locked}
                />
              }
              label="VAD 静音过滤"
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={words}
                  onChange={(e) => setWords(e.target.checked)}
                  disabled={locked}
                />
              }
              label="词级时间戳"
            />
          </AccordionDetails>
        </Accordion>
        <FormControlLabel
          control={
            <Checkbox
              checked={allowDownload}
              onChange={(e) => setAllowDownload(e.target.checked)}
              disabled={locked}
            />
          }
          label={`允许首次下载所选 ${model} 模型（需网络与磁盘空间；已有缓存复用）`}
        />
        <Box mt={1}>
          <Button
            variant="contained"
            disabled={!media || locked || !hw?.ffmpeg || !hw?.ffprobe}
            onClick={() =>
              void execute(async () => {
                if (!media) return;
                startCancelled.current = false;
                setStarting(true);
                try {
                if (dirty) await save();
                if (startCancelled.current) { setNotice("处理已取消"); return; }
                const created = await api<Task>(
                    "/tasks/transcription",
                    json({
                      media_id: media.id,
                      quality,
                      model,
                      device,
                      compute_type: compute,
                      language: language === "auto" ? null : language,
                      beam_size: activeDevice === "metal" ? 1 : beam,
                      vad,
                      word_timestamps: words,
                      allow_download: allowDownload,
                    }),
                  );
                setTask(created);
                activeTaskId.current = created.id;
                if (startCancelled.current) {
                  const cancelled = await api<Task>(`/tasks/${created.id}/cancel`, { method: "POST" });
                  await loadCompletedResult(cancelled);
                  setTask((current) => current?.id === created.id ? mergeVideoTask(current, cancelled) : current);
                }
                } finally { setStarting(false); setProcessCancelBusy(false); }
              })
            }
          >
            {task?.status === "cancelled" ? "重新开始" : "开始识别"}
          </Button>
          {(starting || running(task)) && <Button color="warning" variant="outlined" sx={{ml: 2}}
            disabled={processCancelBusy || task?.status === "cancelling"}
            onClick={() => void cancelProcessing()}>取消处理</Button>}
          {starting && <Typography role="status">{processCancelBusy ? "正在取消处理，等待任务创建返回……" : "正在准备处理……"}</Typography>}
          {task?.status === "cancelled" && !starting && <Typography role="status">处理已取消</Typography>}
          {uploading && <Box mt={2}><Typography role="status">正在上传并解析媒体……</Typography>
            <Button color="warning" onClick={() => { uploadController.current?.abort(); setUploading(false); }}>取消上传</Button></Box>}
        </Box>
      </Paper>
      {[task, videoTask]
        .filter((t) => t && running(t))
        .map(
          (t) =>
            t && (
              <Paper key={t.id} variant="outlined" sx={{ p: 2, mb: 2 }}>
                <Typography mb={1}>
                  {t.status === "pending"
                    ? "排队等待"
                    : t.status === "cancelling" && t.id === task?.id
                      ? stages[t.stage || ""] || "正在取消处理……"
                    : stages[t.stage || ""] || "处理中"}
                  {t.progress !== null
                    ? ` · 已处理音频 ${(t.progress * 100).toFixed(0)}%`
                    : ""}
                </Typography>
                <LinearProgress
                  variant={
                    t.progress === null ? "indeterminate" : "determinate"
                  }
                  value={(t.progress || 0) * 100}
                />
              </Paper>
            ),
        )}
      {result && (
        <Paper variant="outlined" sx={{ p: 3 }}>
          <Stack
            direction="row"
            justifyContent="space-between"
            alignItems="center"
          >
            <Tabs value={tab} onChange={(_, v: number) => setTab(v)}>
              <Tab label={`字幕 (${cues.length})`} />
              <Tab label="纯文本" />
            </Tabs>
            <Button
              disabled={!dirty || locked}
              onClick={() =>
                void execute(async () => {
                  await save();
                  setNotice("修改已保存");
                })
              }
            >
              {dirty ? "保存修改" : "已保存"}
            </Button>
          </Stack>
          {result.message && (
            <Alert severity="info" sx={{ my: 2 }}>
              {result.message}
            </Alert>
          )}
          {tab === 0 ? (
            <>
              <Box className="player" mt={2}>
                {media?.video ? (
                  <>
                    <video
                      ref={player}
                      controls
                      src={`/api/media/${media.id}/content`}
                      onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
                    />
                    {active && <div className="subtitle">{active.text}</div>}
                  </>
                ) : (
                  <audio
                    controls
                    src={`/api/media/${media?.id}/content`}
                    onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
                  />
                )}
              </Box>
              <Box className="cue-list">
                {cues.map((c) => (
                  <Box
                    key={c.id}
                    className={`cue ${active?.id === c.id ? "active" : ""}`}
                  >
                    <Button
                      size="small"
                      onClick={() => {
                        if (player.current)
                          player.current.currentTime = c.start;
                      }}
                    >
                      {clock(c.start)}
                    </Button>
                    <TextField
                      label="开始 / 秒"
                      size="small"
                      type="number"
                      value={c.start}
                      disabled={locked}
                      onChange={(e) => edit(c.id, "start", e.target.value)}
                      slotProps={{ htmlInput: { step: 0.01, min: 0 } }}
                    />
                    <TextField
                      label="结束 / 秒"
                      size="small"
                      type="number"
                      value={c.end}
                      disabled={locked}
                      onChange={(e) => edit(c.id, "end", e.target.value)}
                      slotProps={{ htmlInput: { step: 0.01, min: 0 } }}
                    />
                    <TextField
                      className="cue-text"
                      size="small"
                      multiline
                      value={c.text}
                      disabled={locked}
                      onChange={(e) => edit(c.id, "text", e.target.value)}
                    />
                  </Box>
                ))}
              </Box>
            </>
          ) : (
            <Box mt={2}>
              <Button
                onClick={() =>
                  void execute(async () => {
                    await navigator.clipboard.writeText(text);
                    setNotice("全文已复制");
                  })
                }
              >
                复制全文
              </Button>
              <Box component="pre" className="transcript">
                {text || "没有可识别语音"}
              </Box>
            </Box>
          )}
          <Typography variant="caption" color="text.secondary">
            {result.metrics.model} · {result.metrics.device} /{" "}
            {result.metrics.compute_type} · 实际耗时{" "}
            {result.metrics.elapsed.toFixed(1)} 秒 · RTF{" "}
            {result.metrics.rtf.toFixed(3)}
          </Typography>
          <Stack direction="row" mt={3} alignItems="center" sx={{gap: 2, flexWrap: "wrap"}}>
            <Button
              variant="outlined"
              disabled={busy || !resultTaskId}
              onClick={() =>
                void execute(async () => {
                  await save();
                  await download(
                    `/tasks/${resultTaskId!}/export/txt`,
                    `${base}.txt`,
                  );
                })
              }
            >
              导出 TXT
            </Button>
            <Button
              variant="outlined"
              disabled={busy || !resultTaskId}
              onClick={() =>
                void execute(async () => {
                  await save();
                  await download(
                    `/tasks/${resultTaskId!}/export/srt`,
                    `${base}.srt`,
                  );
                })
              }
            >
              导出 SRT
            </Button>
            <TextField
              select
              size="small"
              label="字幕方式"
              value={exportMode}
              onChange={(e) => setExportMode(e.target.value as "burn" | "mux")}
              disabled={locked}
              sx={{minWidth: 240}}
            >
              <MenuItem value="burn">烧录字幕（MP4）</MenuItem>
              <MenuItem value="mux">外挂字幕封装（MKV，无转码）</MenuItem>
            </TextField>
            {exportMode === "burn" && <TextField
              select
              size="small"
              label="视频编码"
              value={encoder}
              onChange={(e) => setEncoder(e.target.value)}
              disabled={locked}
              sx={{ minWidth: 180 }}
            >
              {(hw?.encoders || ["libx264"]).map((v) => (
                <MenuItem key={v} value={v}>
                  {v === "libx264"
                    ? "H.264 CPU"
                    : v === "h264_nvenc"
                      ? "H.264 NVENC"
                      : v === "h264_videotoolbox"
                        ? "H.264 Apple VideoToolbox"
                        : "HEVC NVENC"}
                </MenuItem>
              ))}
            </TextField>}
            <Button
              variant="contained"
              disabled={locked || !media?.video || (exportMode === "burn" && media.hdr) || !cues.length}
              onClick={() =>
                void execute(async () => {
                  await save();
                  setVideoTask(
                    await api<Task>(
                      `/tasks/${resultTaskId!}/export/video`,
                      json({ encoder, mode: exportMode }),
                    ),
                  );
                })
              }
            >
              {videoTask?.status === "cancelled" ? "重新导出" : exportMode === "mux" ? "导出 MKV" : "导出 MP4"}
            </Button>
            {videoTask && running(videoTask) && (
              <>
                <Typography role="status">
                  {cancelBusy || videoTask.status === "cancelling" ? "正在取消导出……" : "正在导出视频……"}
                </Typography>
                <Button color="warning" variant="outlined"
                  disabled={cancelBusy || videoTask.status === "cancelling" || videoTask.stage === "finalizing"}
                  onClick={() => void cancelExport()}>
                  取消导出
                </Button>
              </>
            )}
            {videoTask?.status === "cancelled" && <Typography role="status">视频导出已取消</Typography>}
            {videoTask?.status === "completed" && (
              <Button
                onClick={() =>
                  void execute(async () =>
                    download(
                      `/exports/${videoTask.id}/content`,
                      `${base}_subtitled.${videoTask.output_format || "mp4"}`,
                    ),
                  )
                }
              >
                下载已导出视频
              </Button>
            )}
          </Stack>
          {exportMode === "mux" && <Typography variant="body2" color="text.secondary" mt={2}>
            将编辑后的字幕作为可开关的字幕轨道封装到 MKV；原视频、全部音轨直接复制，不转码，支持保留 HDR。需使用支持 MKV 字幕的播放器。
          </Typography>}
        </Paper>
      )}
    </Container>
  );
}
