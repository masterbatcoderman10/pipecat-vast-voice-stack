const DEFAULT_REALTIME_WS_URL = 'ws://127.0.0.1:7860/v2/realtime/ws';

function randomSessionId() {
  const cryptoObject = globalThis.crypto;
  if (cryptoObject?.randomUUID) return cryptoObject.randomUUID();
  return `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function float32ToPcm16(samples) {
  const buffer = new ArrayBuffer(samples.length * 2);
  const view = new DataView(buffer);

  for (let index = 0; index < samples.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, samples[index] || 0));
    const value = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
    view.setInt16(index * 2, Math.round(value), true);
  }

  return buffer;
}

export function buildSessionStart({ voice = 'clone:sylens', session_id } = {}) {
  return {
    type: 'session.start',
    session_id: session_id || randomSessionId(),
    sample_rate: 16000,
    channels: 1,
    encoding: 'pcm_s16le',
    voice,
  };
}

export function nextRealtimeWsUrl(v1Url) {
  if (!v1Url) return DEFAULT_REALTIME_WS_URL;
  if (v1Url.includes('/v2/realtime/ws')) return v1Url;
  return v1Url.replace('/v1/voice-turn/ws', '/v2/realtime/ws');
}

function ensureBrowserWebSocket(WebSocketImpl) {
  const Impl = WebSocketImpl || globalThis.WebSocket;
  if (!Impl) throw new Error('WebSocket is not available in this environment');
  return Impl;
}

export class RealtimeVoiceClient {
  constructor({ url, voice = 'clone:sylens', onEvent = () => {}, onAudio = () => {}, onError = () => {}, WebSocketImpl } = {}) {
    this.url = nextRealtimeWsUrl(url);
    this.voice = voice;
    this.onEvent = onEvent;
    this.onAudio = onAudio;
    this.onError = onError;
    this.WebSocketImpl = WebSocketImpl;
    this.ws = null;
    this.ready = false;
    this._openPromise = null;
  }

  connect() {
    if (this._openPromise) return this._openPromise;

    const WebSocketCtor = ensureBrowserWebSocket(this.WebSocketImpl);
    this.ws = new WebSocketCtor(this.url);
    this.ws.binaryType = 'arraybuffer';

    this._openPromise = new Promise((resolve, reject) => {
      this.ws.onopen = () => {
        this.ready = true;
        this._sendJson(buildSessionStart({ voice: this.voice }));
        resolve(this);
      };

      this.ws.onerror = (event) => {
        this.onError(event);
        reject(new Error('websocket failed'));
      };
    });

    this.ws.onmessage = async (message) => {
      if (typeof message.data === 'string') {
        this.onEvent(JSON.parse(message.data));
        return;
      }
      this.onAudio(message.data);
    };

    this.ws.onclose = () => {
      this.ready = false;
    };

    return this._openPromise;
  }

  sendPcmChunk(chunk) {
    if (!chunk || chunk.byteLength === 0) return;
    this._sendBinary(chunk);
  }

  commit() {
    this._sendJson({ type: 'audio.input.commit' });
  }

  cancel() {
    this._sendJson({ type: 'response.cancel' });
  }

  close() {
    if (this.ws && this.ws.readyState <= 1) this.ws.close();
    this.ready = false;
    this.ws = null;
    this._openPromise = null;
  }

  _sendJson(payload) {
    this._sendString(JSON.stringify(payload));
  }

  _sendString(payload) {
    if (!this.ws || this.ws.readyState !== 1) return;
    this.ws.send(payload);
  }

  _sendBinary(payload) {
    if (!this.ws || this.ws.readyState !== 1) return;
    this.ws.send(payload);
  }
}

export async function createAudioWorkletStreamer({ audioContext, stream, onChunk }) {
  if (!audioContext?.audioWorklet) throw new Error('AudioWorklet is not available');
  if (!stream) throw new Error('MediaStream is required');
  if (typeof onChunk !== 'function') throw new Error('onChunk callback is required');

  await audioContext.audioWorklet.addModule('/pcm-worklet.js');
  const source = audioContext.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(audioContext, 'pcm-worklet');
  const sink = audioContext.createGain();
  sink.gain.value = 0;

  node.port.onmessage = (event) => {
    if (event.data?.type === 'pcm' && event.data.buffer) onChunk(event.data.buffer);
  };

  source.connect(node);
  node.connect(sink);
  sink.connect(audioContext.destination);

  return {
    node,
    source,
    stop() {
      node.port.onmessage = null;
      source.disconnect();
      node.disconnect();
      sink.disconnect();
    },
  };
}
