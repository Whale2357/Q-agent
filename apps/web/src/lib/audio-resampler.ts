/** Area-average PCM conversion with fractional state preserved across callbacks. */
export class PcmResampler {
  private readonly ratio: number;
  private weight = 0;
  private area = 0;

  constructor(inputRate: number, outputRate = 16_000) {
    if (!Number.isFinite(inputRate) || inputRate <= 0 || !Number.isFinite(outputRate) || outputRate <= 0) throw new Error("Invalid sample rate");
    this.ratio = inputRate / outputRate;
  }

  process(input: Float32Array): Float32Array {
    const output = new Float32Array(Math.ceil((input.length + this.weight) / this.ratio));
    let count = 0;
    for (const sample of input) {
      let remaining = 1;
      while (remaining > 1e-9) {
        const consumed = Math.min(remaining, this.ratio - this.weight);
        this.area += (Number.isFinite(sample) ? sample : 0) * consumed;
        this.weight += consumed;
        remaining -= consumed;
        if (this.weight >= this.ratio - 1e-9) {
          output[count++] = Math.max(-1, Math.min(1, this.area / this.ratio));
          this.weight = 0;
          this.area = 0;
        }
      }
    }
    return output.slice(0, count);
  }
}
