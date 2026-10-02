// Protege todo el dashboard con usuario y contraseña (autenticación básica del navegador).
// La contraseña se configura en Vercel: Settings → Environment Variables → DASHBOARD_PASSWORD
export const config = { matcher: "/(.*)" };

export default function middleware(request) {
  const clave = process.env.DASHBOARD_PASSWORD;
  if (!clave) {
    return new Response("Falta configurar DASHBOARD_PASSWORD en Vercel.", { status: 503 });
  }
  const auth = request.headers.get("authorization") || "";
  const [tipo, codificado] = auth.split(" ");
  if (tipo === "Basic" && codificado) {
    const texto = atob(codificado);
    const pwd = texto.slice(texto.indexOf(":") + 1);
    if (pwd === clave) return; // acceso permitido
  }
  return new Response("Acceso restringido", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="CazaVuelos", charset="UTF-8"' },
  });
}
