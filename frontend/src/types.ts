export interface Media {
  id: string;
  name: string;
  duration: number;
  size: number;
  video: boolean;
  hdr: boolean;
  width: number | null;
  height: number | null;
}
export interface Cue {
  id: number;
  group: number;
  start: number;
  end: number;
  text: string;
  join_before?: string | null;
}
export interface Task {
  id: string;
  status: "pending" | "processing" | "cancelling" | "cancelled" | "completed" | "failed";
  stage: string | null;
  progress: number | null;
  error: string | null;
  output_format?: "mp4" | "mkv" | null;
}
export interface Result {
  cues: Cue[];
  text: string;
  language: string;
  message: string | null;
  metrics: {
    model: string;
    device: string;
    compute_type: string;
    elapsed: number;
    rtf: number;
  };
}
export interface Hardware {
  apple_silicon?: boolean;
  inference_note?: string;
  gpu: { name: string; memory_mb: number }[];
  cuda: boolean;
  ffmpeg: boolean;
  ffprobe: boolean;
  compute_types: { cpu: string[]; cuda: string[] };
  encoders: string[];
  warnings: string[];
}
