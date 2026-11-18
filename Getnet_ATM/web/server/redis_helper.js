// Crea un RedisStore sobre ioredis-mock (sin Redis real). Devuelve null si no es posible.
export async function mockRedisStore() {
  try {
    const { default: RedisMock } = await import('ioredis-mock');
    // ioredis-mock 8 usa transformadores de respuesta de ioredis 5; con ioredis 6 fallan (context.protocol).
    // Sin WITHSCORES la respuesta de zrange ya es una lista plana, así que se desactiva ese transformador.
    const ioredis = await import('ioredis');
    const Command = ioredis.Command ?? ioredis.default?.Command;
    if (Command?._transformer?.reply) delete Command._transformer.reply.zrange;
    const { RedisStore } = await import('./store.js');
    const s = new RedisStore(undefined, new RedisMock());
    await s.connect();
    return s;
  } catch (e) {
    console.warn(`AVISO: ioredis-mock no disponible (${e.message}); se omite RedisStore.`);
    return null;
  }
}
