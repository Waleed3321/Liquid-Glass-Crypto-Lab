const TARGET = process.env.API_BASE_URL ?? "https://liquid-glass-crypto-lab.onrender.com";

export default async function keepalive(_request: Request): Promise<Response> {
  const started = Date.now();
  try {
    const response = await fetch(`${TARGET}/api/v1/health`, {
      signal: AbortSignal.timeout(120_000),
    });
    const body = await response.text();
    return Response.json({
      ok: response.ok,
      status: response.status,
      ms: Date.now() - started,
      health: body.slice(0, 240),
    });
  } catch (error) {
    return Response.json(
      { ok: false, error: String(error), ms: Date.now() - started },
      { status: 502 },
    );
  }
}
