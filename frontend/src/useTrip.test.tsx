import { it, expect, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useTrip } from './useTrip';
const state = (status:string) => ({trip_id:'abc',status,current_task:status==='running'?'research':null,created_at:new Date().toISOString(),started_at:null,finished_at:null,events:[],events_total:0,error:null});
const response=(data:unknown,status=200)=>new Response(JSON.stringify(data),{status});
it('polls sequentially, waits after replies, and stops after completion', async()=>{
  vi.useFakeTimers(); let release!:(v:Response)=>void;
  const fetcher=vi.fn().mockImplementationOnce(()=>new Promise<Response>(resolve=>{release=resolve})).mockResolvedValueOnce(response(state('completed'))).mockResolvedValueOnce(response({trip_id:'abc',final:{},tasks:{}}));
  vi.stubGlobal('fetch',fetcher);
  const {result,unmount}=renderHook(()=>useTrip('abc'));
  await act(async()=>{await vi.advanceTimersByTimeAsync(5000)});
  expect(fetcher).toHaveBeenCalledTimes(1);
  await act(async()=>{release(response(state('running'))); await Promise.resolve()});
  await act(async()=>{await vi.advanceTimersByTimeAsync(2000)});
  expect(result.current.state?.status).toBe('completed'); expect(result.current.result?.trip_id).toBe('abc');
  const count=fetcher.mock.calls.length;
  await act(async()=>{await vi.advanceTimersByTimeAsync(8000)});
  expect(fetcher).toHaveBeenCalledTimes(count); unmount();
});
it('pauses on network failure, resumes GET without POST, and aborts on unmount',async()=>{
  vi.useFakeTimers(); const fetcher=vi.fn().mockRejectedValueOnce(new TypeError('offline')).mockResolvedValueOnce(response(state('running'))).mockImplementationOnce((_url:string,options:RequestInit)=>new Promise<Response>((_resolve,reject)=>options.signal?.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')))));
  vi.stubGlobal('fetch',fetcher);
  const {result,unmount}=renderHook(()=>useTrip('abc'));
  await act(async()=>{await Promise.resolve()}); expect(result.current.issue?.kind).toBe('network');
  await act(async()=>{await vi.advanceTimersByTimeAsync(6000)}); expect(fetcher).toHaveBeenCalledTimes(1);
  await act(async()=>{result.current.resume(); await Promise.resolve()}); expect(result.current.state?.status).toBe('running');
  await act(async()=>{await vi.advanceTimersByTimeAsync(2000)});
  const signal=fetcher.mock.calls[2][1].signal as AbortSignal; unmount(); expect(signal.aborted).toBe(true);
  expect(fetcher.mock.calls.every(c=>!c[1]?.method || c[1].method==='GET')).toBe(true);
});
it('stops on failed and explains a lost 404 history',async()=>{
  vi.useFakeTimers(); const fetcher=vi.fn().mockResolvedValueOnce(response(state('failed')));vi.stubGlobal('fetch',fetcher);
  const first=renderHook(()=>useTrip('abc'));await act(async()=>{await Promise.resolve();await vi.advanceTimersByTimeAsync(6000)});
  expect(first.result.current.state?.status).toBe('failed');expect(fetcher).toHaveBeenCalledTimes(1);first.unmount();
  fetcher.mockResolvedValueOnce(response({detail:{code:'trip_not_found'}},404));
  const second=renderHook(()=>useTrip('lost'));await act(async()=>{await Promise.resolve()});expect(second.result.current.issue?.kind).toBe('missing');
});
