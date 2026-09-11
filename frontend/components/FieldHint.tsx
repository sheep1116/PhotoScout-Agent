'use client';
import {useEffect, useId, useRef, useState} from 'react';
import {Info} from 'lucide-react';

export default function FieldHint({label,children}:{label:string;children:React.ReactNode}) {
  const id=useId(),root=useRef<HTMLSpanElement>(null);
  const dismiss=useRef<ReturnType<typeof setTimeout>|null>(null);
  const [open,setOpen]=useState(false);
  useEffect(()=>{
    if(!open)return;
    const close=(event:PointerEvent)=>{if(!root.current?.contains(event.target as Node))setOpen(false);};
    document.addEventListener('pointerdown',close);
    return ()=>document.removeEventListener('pointerdown',close);
  },[open]);
  useEffect(()=>()=>{if(dismiss.current)clearTimeout(dismiss.current);},[]);
  return <span ref={root} className="field-hint" onMouseEnter={()=>{if(dismiss.current)clearTimeout(dismiss.current);setOpen(true);}} onMouseLeave={()=>{dismiss.current=setTimeout(()=>setOpen(false),150);}} onKeyDown={e=>{if(e.key==='Escape'){e.stopPropagation();setOpen(false);}}}>
    <button type="button" className="hint-trigger" aria-label={label} aria-expanded={open} aria-describedby={open?id:undefined} onFocus={()=>setOpen(true)} onBlur={()=>setOpen(false)} onClick={e=>{e.preventDefault();setOpen(true);}}><Info size={13}/></button>
    {open&&<span className="hint-bubble" id={id} role="tooltip">{children}</span>}
  </span>;
}
