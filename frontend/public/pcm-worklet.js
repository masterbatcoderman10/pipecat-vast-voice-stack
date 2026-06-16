class PcmWorkletProcessor extends AudioWorkletProcessor {
  float32ToPcm16(samples) {
    const buffer = new ArrayBuffer(samples.length * 2);
    const view = new DataView(buffer);

    for (let index = 0; index < samples.length; index += 1) {
      const sample = Math.max(-1, Math.min(1, samples[index] || 0));
      const value = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      view.setInt16(index * 2, Math.round(value), true);
    }

    return buffer;
  }

  process(inputs) {
    const input = inputs[0];
    const channel = input?.[0];
    if (!channel || channel.length === 0) return true;

    const buffer = this.float32ToPcm16(channel);
    this.port.postMessage({ type: 'pcm', buffer }, [buffer]);
    return true;
  }
}

registerProcessor('pcm-worklet', PcmWorkletProcessor);
