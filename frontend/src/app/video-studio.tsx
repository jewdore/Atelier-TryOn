'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowDownToLine, Check, Film, LoaderCircle, Upload } from 'lucide-react';

type Garment = { id: string; name: string; category: string; image_url: string };
type Video = { video_id: string; preview_url: string; duration_seconds: number; fps: number; width: number; height: number };
type Job = { job_id: string; status: string; result_url?: string; latency_ms?: number; error?: string; phase?: string; progress?: number };
const phases: Record<string, string> = { queued: '等待视频 GPU', preprocess: '分析人物与服装区域', inference: '生成时序一致的换装视频', encoding: '编码 MP4', completed: '换装完成' };

async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, { cache: 'no-store', ...options });
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `请求失败 (${response.status})`);
  return body;
}

export default function VideoStudio({ garments }: { garments: Garment[] }) {
  const [video, setVideo] = useState<Video>();
  const [result, setResult] = useState('');
  const [selected, setSelected] = useState('');
  const [uploading, setUploading] = useState(false);
  const [job, setJob] = useState<Job>();
  const [error, setError] = useState('');
  const [original, setOriginal] = useState(false);
  const [workers, setWorkers] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const controller = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const session = useRef('');
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    session.current = `video-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    let mounted = true;
    const health = async () => {
      try { const response = await fetch('/api/health'); const body = await response.json(); if (mounted) setWorkers(body.video_workers || 0); } catch { if (mounted) setWorkers(0); }
    };
    health();
    const interval = setInterval(health, 10000);
    return () => { mounted = false; sequence.current++; controller.current?.abort(); clearInterval(interval); if (timer.current) clearTimeout(timer.current); };
  }, []);

  function reset(): { version: number; abort: AbortController } {
    controller.current?.abort();
    if (timer.current) clearTimeout(timer.current);
    const abort = new AbortController();
    controller.current = abort;
    setJob(undefined); setResult(''); setError(''); setOriginal(false);
    return { version: ++sequence.current, abort };
  }

  async function upload(file?: File) {
    if (!file) return;
    if (!/\.(mp4|mov|webm)$/i.test(file.name) || file.size > 100 * 1024 * 1024) {
      setError('请选择不超过 100MB 的 MP4、MOV 或 WebM 视频'); return;
    }
    const { version, abort } = reset();
    setUploading(true); setVideo(undefined); setSelected('');
    try {
      const uploaded = await api<Video>('/api/videos', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file, signal: abort.signal });
      if (sequence.current === version) setVideo(uploaded);
    } catch (reason) {
      if (!abort.signal.aborted && sequence.current === version) setError(reason instanceof Error ? reason.message : '上传失败');
    } finally { if (sequence.current === version) setUploading(false); }
  }

  function choose(garment: Garment) {
    if (!video) { input.current?.click(); return; }
    const { version, abort } = reset();
    setSelected(garment.id); setJob({ job_id: '', status: 'queued', phase: 'queued', progress: 0 });
    timer.current = setTimeout(async () => {
      try {
        const submitted = await api<Job>('/api/tryon/video', { method: 'POST', signal: abort.signal,
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ video_id: video.video_id,
            garment_id: garment.id, category: garment.category, session_id: session.current, sequence: version }) });
        const deadline = Date.now() + 3700000;
        while (version === sequence.current && !abort.signal.aborted) {
          if (Date.now() > deadline) throw new Error('等待超时，请稍后查看或重新提交');
          const state = await api<Job>(`/api/tryon/${submitted.job_id}`, { signal: abort.signal });
          if (version !== sequence.current) return;
          setJob(state);
          if (state.status === 'failed') throw new Error(state.error || '视频生成失败');
          if (state.status === 'completed' && state.result_url) { setResult(state.result_url); return; }
          await new Promise(resolve => setTimeout(resolve, 1200));
        }
      } catch (reason) {
        if (version === sequence.current && !abort.signal.aborted) { setError(reason instanceof Error ? reason.message : '视频生成失败'); setJob(undefined); }
      }
    }, 180);
  }

  const busy = job?.status === 'queued' || job?.status === 'running';
  return <>
    <div className="video-notice"><Film size={17}/><span>视频换装 · CatV2TON · {workers ? `${workers} 个独立视频 GPU 已就绪` : '视频模型准备中'}<small>单人短视频，0.34–8 秒 / 100MB；输出 384 × 512、12 FPS、无音轨。当前仅支持上装，非实时直播。</small></span></div>
    <div className="workspace">
      <section className="canvas-panel">
        <div className="panel-heading"><div><span className="step">01</span><strong>视频试衣镜</strong></div><button className="text-button" onClick={() => input.current?.click()}><Upload size={15}/>更换视频</button></div>
        <div className={`canvas ${video ? 'has-person' : ''}`} onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); upload(event.dataTransfer.files[0]); }}>
          {video ? <video key={original || !result ? video.preview_url : result} className="person-image" src={original || !result ? video.preview_url : result} controls playsInline loop preload="metadata"/> : <div className="empty-state"><Film size={55}/><h2>让新造型，动起来</h2><p>上传单人视频，再选择一件上装。<br/>建议正面、动作平缓、衣物无遮挡。</p><button className="primary" disabled={uploading} onClick={() => input.current?.click()}><Upload size={18}/>{uploading ? '正在上传并校验…' : '上传人物视频'}</button><small>MP4 / MOV / WebM · 最长 8 秒</small></div>}
          {(uploading || busy) && <div className="generating video-generating"><LoaderCircle className="animate-spin" size={19}/><div>{uploading ? '上传、解码与校验视频' : phases[job?.phase || 'queued'] || '视频处理中'}<small>{busy ? `${job?.progress || 0}% · 阶段进度，非精确剩余时间 · 可继续切换单品` : '请稍候'}</small></div></div>}
        </div>
        <div className="canvas-footer"><span>{video ? `${video.duration_seconds.toFixed(2)}s · ${video.width} × ${video.height} · ${video.fps} FPS` : '上传一次，可以反复选择不同衣服'}</span><span>{job?.latency_ms ? `${(job.latency_ms / 1000).toFixed(1)}s` : 'VIDEO TRY-ON'}</span></div>
        {result && <div className="video-actions"><button onClick={() => setOriginal(!original)}>{original ? '查看换装视频' : '查看原始视频'}</button><a href={result} download="atelier-video-tryon.mp4"><ArrowDownToLine size={16}/>下载 MP4</a></div>}
        {job?.job_id && <p className="video-job">任务：{job.job_id}</p>}
      </section>
      <aside className="closet-panel"><div className="panel-heading"><div><span className="step">02</span><strong>选择视频中的新上装</strong></div></div><p className="closet-caption">上传完成后，点击单品开始视频换装。</p><div className="garment-grid">{garments.filter(item => item.category === 'upper_body').map(garment => <button key={garment.id} disabled={uploading || !workers} className={`garment ${selected === garment.id ? 'selected' : ''}`} aria-pressed={selected === garment.id} onClick={() => choose(garment)}><div className="garment-photo"><img src={garment.image_url} alt={garment.name}/>{selected === garment.id && <span className="selected-check"><Check size={13}/></span>}</div><div className="garment-name">{garment.name}</div></button>)}</div><div className="closet-tip"><p><strong>只展示最后选择的结果</strong><br/>尚未运行的旧任务会被替换；已运行任务允许完成，但不会覆盖新选择。视频生成耗时高于图片，请耐心等待。</p></div></aside>
    </div>
    {error && <div className="error" role="alert">{error}<button onClick={() => setError('')}>关闭</button></div>}
    <input ref={input} type="file" accept="video/mp4,video/quicktime,video/webm,.mov" className="hidden" aria-label="上传人物视频" onChange={event => { upload(event.target.files?.[0]); event.target.value = ''; }}/>
  </>;
}
