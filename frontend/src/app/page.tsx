'use client';

import { useEffect, useRef, useState } from 'react';
import VideoStudio from './video-studio';
import './video.css';
import { ArrowDownToLine, ArrowUpRight, Camera, Check, ChevronRight, ImagePlus, LoaderCircle, Plus, RotateCcw, Shirt, Sparkles, Upload, X } from 'lucide-react';

type Garment = { id: string; name: string; category: string; image_url: string };
type Job = { job_id: string; status: string; error?: string; result_url?: string; latency_ms?: number };
const filters = [{ id: 'all', name: '全部单品' }, { id: 'upper_body', name: '上装' }, { id: 'dresses', name: '连衣裙' }, { id: 'lower_body', name: '裤装' }];

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, { cache: 'no-store', ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败 (${response.status})`);
  return data;
}

export default function Studio() {
  const [mode, setMode] = useState<'image' | 'video'>('image');
  const [garments, setGarments] = useState<Garment[]>([]);
  const [person, setPerson] = useState('');
  const [result, setResult] = useState('');
  const [selected, setSelected] = useState('');
  const [filter, setFilter] = useState('all');
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [latency, setLatency] = useState<number>();
  const [original, setOriginal] = useState(false);
  const [workers, setWorkers] = useState(0);
  const [mock, setMock] = useState(false);
  const sequence = useRef(0);
  const session = useRef('');
  const controller = useRef<AbortController | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const cameraInput = useRef<HTMLInputElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const uploadVersion = useRef(0);

  useEffect(() => {
    session.current = globalThis.crypto?.randomUUID?.() || `session-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    request<Garment[]>('/api/garments').then(setGarments).catch((reason: Error) => setError(reason.message));
    const health = async () => {
      try {
        const response = await fetch('/api/health', { cache: 'no-store' });
        const data = await response.json();
        setWorkers(data.ready_workers || 0);
        setMock(data.workers?.some((worker: { model: string }) => worker.model === 'mock') || false);
      } catch { setWorkers(0); }
    };
    void health();
    const interval = setInterval(health, 10000);
    return () => { clearInterval(interval); controller.current?.abort(); if (timer.current) clearTimeout(timer.current); sequence.current++; };
  }, []);

  function upload(file?: File) {
    if (!file) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 20 * 1024 * 1024) {
      setError('请选择 20MB 以内的 JPG、PNG 或 WebP 图片'); return;
    }
    const version = ++uploadVersion.current;
    ++sequence.current;
    controller.current?.abort();
    if (timer.current) clearTimeout(timer.current);
    setStatus(''); setSelected(''); setResult(''); setError(''); setLatency(undefined);
    const reader = new FileReader();
    reader.onload = () => { if (version === uploadVersion.current) setPerson(String(reader.result)); };
    reader.onerror = () => setError('图片读取失败，请重新选择');
    reader.readAsDataURL(file);
  }

  function choose(garment: Garment) {
    if (!person) { fileInput.current?.click(); return; }
    const current = ++sequence.current;
    controller.current?.abort();
    if (timer.current) clearTimeout(timer.current);
    const abort = new AbortController();
    controller.current = abort;
    setSelected(garment.id); setStatus('queued'); setError(''); setOriginal(false); setLatency(undefined);
    timer.current = setTimeout(async () => {
      try {
        const job = await request<Job>('/api/tryon', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: abort.signal,
          body: JSON.stringify({ person_image: person, garment_id: garment.id, category: garment.category,
            session_id: session.current, sequence: current }),
        });
        const deadline = Date.now() + 420000;
        while (current === sequence.current && !abort.signal.aborted) {
          if (Date.now() > deadline) throw new Error('生成等待超时，请重试');
          const state = await request<Job>(`/api/tryon/${job.job_id}`, { signal: abort.signal });
          if (current !== sequence.current) return;
          setStatus(state.status);
          if (state.status === 'failed') throw new Error(state.error || '生成失败，请重试');
          if (state.status === 'completed' && state.result_url) {
            setResult(state.result_url); setLatency(state.latency_ms); setStatus(''); return;
          }
          await new Promise(resolve => setTimeout(resolve, 450));
        }
      } catch (reason) {
        if (current === sequence.current && !abort.signal.aborted) {
          setError(reason instanceof Error ? reason.message : '生成失败'); setStatus('');
        }
      }
    }, 140);
  }

  const active = garments.find(garment => garment.id === selected);
  const visible = garments.filter(garment => filter === 'all' || garment.category === filter);

  return <main>
    <header className="topbar">
      <a className="brand" href="/"><span className="brand-icon"><Shirt size={21}/></span> ATELIER<span className="brand-divider"/> <span className="brand-description">VIRTUAL TRY-ON STUDIO</span></a>
      <div className="service"><i className={workers ? 'online' : ''}/>{mock ? 'MOCK · 非真实换衣' : workers ? `${workers} GPU workers ready` : '模型准备中'}<span className="version">V1.0</span></div>
    </header>
    <section className="heading"><div><div className="eyebrow">YOUR PERSONAL FITTING ROOM</div><h1>换一种穿搭，<span>发现新的自己。</span></h1><p>一张照片，即刻试穿。点击右侧单品，探索属于你的风格。</p></div><div className="privacy"><Sparkles size={17}/><span>Powered by CatVTON<br/><small>照片临时保存 · 到期自动清理</small></span></div></section>
    <nav className="mode-tabs" aria-label="换装模式"><button className={mode === 'image' ? 'active' : ''} onClick={() => setMode('image')}>图片换装</button><button className={mode === 'video' ? 'active' : ''} onClick={() => setMode('video')}>视频换装 <span>NEW</span></button></nav>
    {mode === 'video' && <VideoStudio garments={garments}/>}
    <div className="workspace" style={mode === 'video' ? { display: 'none' } : undefined}>
      <section className="canvas-panel">
        <div className="panel-heading"><div><span className="step">01</span><strong>试衣镜</strong><span className="muted">Your look</span></div><button className="text-button" onClick={() => fileInput.current?.click()}><Upload size={15}/>更换照片</button></div>
        <div className={`canvas ${person ? 'has-person' : ''}`} onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); upload(event.dataTransfer.files[0]); }}>
          {person ? <img className="person-image" src={original || !result ? person : result} alt={original || !result ? '上传的人物照片' : '虚拟试穿效果'} /> : <div className="empty-state"><div className="portrait-outline"><div className="portrait-head"/><div className="portrait-body"/><span><Plus size={23}/></span></div><h2>从一张你的照片开始</h2><p>上传正面全身或半身照，<br/>让每一件衣服，都有你的样子。</p><button className="primary" onClick={() => fileInput.current?.click()}><ImagePlus size={18}/>上传人物照片<ArrowUpRight size={17}/></button><button className="camera-button" onClick={() => cameraInput.current?.click()}><Camera size={16}/>使用相机拍摄</button><small>JPG / PNG / WebP · 最大 20MB</small></div>}
          {person && <span className="canvas-tag">{original || !result ? 'ORIGINAL' : 'YOUR NEW LOOK'}</span>}
          {status && <div className="generating"><LoaderCircle className="animate-spin" size={19}/><div>{status === 'queued' ? '正在排队，马上为你试穿' : '正在生成你的新造型'}<small>{active?.name} · 可以继续切换单品</small></div></div>}
          {result && !status && <div className="result-tools"><button onPointerDown={() => setOriginal(true)} onPointerUp={() => setOriginal(false)} onPointerLeave={() => setOriginal(false)} onFocus={() => setOriginal(true)} onBlur={() => setOriginal(false)}><RotateCcw size={15}/>按住对比原图</button><a href={result} download="atelier-tryon.png"><ArrowDownToLine size={16}/>保存图片</a></div>}
        </div>
        <div className="canvas-footer"><span><span className="tiny-dot"/>{person ? active?.name || '照片已就绪，选择一件喜欢的单品' : '建议：单人正面照，光线均匀，服装无遮挡'}</span><span>{latency ? `${(latency / 1000).toFixed(2)}s` : 'IMAGE TRY-ON'}</span></div>
      </section>
      <aside className="closet-panel"><div className="panel-heading"><div><span className="step">02</span><strong>我的衣橱</strong></div><span className="count">{garments.length} 单品</span></div><p className="closet-caption">找到心仪的单品，点击即可试穿。</p><div className="filters">{filters.map(item => <button key={item.id} className={filter === item.id ? 'active' : ''} onClick={() => setFilter(item.id)}>{item.name}</button>)}</div><div className="garment-grid">{visible.map((garment, index) => <button key={garment.id} className={`garment ${selected === garment.id ? 'selected' : ''}`} onClick={() => choose(garment)} aria-pressed={selected === garment.id}><div className="garment-photo"><img src={garment.image_url} alt={garment.name}/>{selected === garment.id ? <span className="selected-check"><Check size={13}/></span> : <span className="try-icon"><Plus size={14}/></span>}{index === 0 && <span className="item-label">ESSENTIAL</span>}</div><div className="garment-name">{garment.name}</div><div className="garment-kind">{garment.category === 'dresses' ? 'DRESSES' : garment.category === 'lower_body' ? 'BOTTOMS' : 'TOPS & LAYERS'}<ChevronRight size={12}/></div></button>)}</div>{garments.length === 0 && <div className="closet-empty"><Shirt size={30}/><p>衣橱准备中</p><small>在 garments 目录添加服装图片</small></div>}<div className="closet-tip"><Sparkles size={17}/><p><strong>随心切换，不必等待</strong><br/>连续点击时，只展示你最后选择的造型。</p></div></aside>
    </div>
    {error && <div className="error" role="alert">{error}<button aria-label="关闭提示" onClick={() => setError('')}><X size={17}/></button></div>}
    <footer><span>ATELIER — A NEW WAY TO GET DRESSED.</span><span>Image-first. Style-forward.</span></footer>
    <input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" aria-label="上传人物照片" onChange={event => { upload(event.target.files?.[0]); event.target.value = ''; }}/>
    <input ref={cameraInput} type="file" accept="image/*" capture="user" className="hidden" aria-label="拍摄人物照片" onChange={event => { upload(event.target.files?.[0]); event.target.value = ''; }}/>
  </main>;
}
