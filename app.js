/**
 * BUSCADOR DE ACTAS - FUNDACIÓN CARDIOVASCULAR DE COLOMBIA (FCV)
 * Proceso: Ciberseguridad FCV DevSecOps
 * 
 * Mitigaciones y Arquitectura de Seguridad Implementadas:
 * - Autenticación Segura en Servidor (Server-Side Auth con SQLite en server.py).
 * - Cero credenciales ni hashes expuestos en el código cliente (Mitigación CWE-798 / CWE-259).
 * - CWE-693 / CWE-79: Cero inyecciones DOM XSS. Construcción programática 100% nativa.
 * - CWE-1021: Anti-Clickjacking mediante cabeceras HTTP y frame-busting en cliente.
 * - CWE-345 / CWE-200: Operación local 100% aislada. Cero dependencias externas o CDNs sin SRI.
 * - CWE-497: Ofuscación y supresión de banners de versión de software.
 * - Paginación eficiente en cliente: Alto rendimiento para los 746 registros sin saturación del DOM.
 * - Cero banderas o marcas "Revisar" en las actas (registros limpios y normalizados).
 * - Soporte completo de accesibilidad e identidad visual FCV (Light / Dark Mode).
 */

// Protección Anti-Clickjacking complementaria en cliente (CWE-1021)
if (window.top !== window.self) {
  window.top.location = window.self.location;
}

// ============================================================================
// 1. GESTION DE TEMA VISUAL (LIGHT / DARK MODE)
// ============================================================================
const ThemeManager = (function () {
  'use strict';
  const STORAGE_KEY = 'fcv_actas_theme';

  function aplicarTema(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) {}
    actualizarIconos(theme);
  }

  function actualizarIconos(theme) {
    const sun = document.getElementById('themeIconSun');
    const moon = document.getElementById('themeIconMoon');
    if (!sun || !moon) return;

    if (theme === 'dark') {
      sun.classList.remove('hidden');
      moon.classList.add('hidden');
    } else {
      sun.classList.add('hidden');
      moon.classList.remove('hidden');
    }
  }

  function obtenerTemaInicial() {
    try {
      const guardado = localStorage.getItem(STORAGE_KEY);
      if (guardado === 'dark' || guardado === 'light') return guardado;
    } catch (e) {}

    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return 'dark';
    }
    return 'light';
  }

  function toggle() {
    const actual = document.documentElement.getAttribute('data-theme') || 'light';
    const nuevo = actual === 'dark' ? 'light' : 'dark';
    aplicarTema(nuevo);
  }

  return {
    init() {
      const inicial = obtenerTemaInicial();
      aplicarTema(inicial);
      const btn = document.getElementById('themeToggleBtn');
      if (btn) {
        btn.addEventListener('click', toggle);
      }
    }
  };
})();

// ============================================================================
// 2. SERVICIO DE AUTENTICACION SEGURO (AuthService - Server-Side API)
// ============================================================================
const AuthService = (function () {
  'use strict';

  const STORAGE_KEY = 'fcv_actas_auth_session';
  const INACTIVITY_TIMEOUT_MS = 15 * 60 * 1000; // 15 minutos
  let inactivityTimer = null;

  return {
    /**
     * Autentica contra el endpoint del servidor backend (/api/login).
     * No expone credenciales, hashes ni lógica de validación en el cliente.
     */
    async authenticate(username, password) {
      const cleanUser = (username || '').trim().toLowerCase();
      const cleanPass = (password || '').trim();

      if (!cleanUser || !cleanPass) {
        return { success: false, message: 'Por favor ingrese su usuario y contraseña institucional.' };
      }

      try {
        const response = await fetch('/api/login', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            username: cleanUser,
            password: cleanPass
          })
        });

        const data = await response.json();
        if (response.ok && data.success) {
          const sessionData = {
            token: data.user.token,
            username: data.user.username,
            name: data.user.name,
            role: data.user.role,
            loginTime: Date.now()
          };
          sessionStorage.setItem(STORAGE_KEY, JSON.stringify(sessionData));
          return { success: true, user: sessionData };
        } else {
          return {
            success: false,
            locked: data.locked || false,
            message: data.message || 'Credenciales inválidas. Verifique sus datos de acceso.'
          };
        }
      } catch (err) {
        return {
          success: false,
          message: 'Error de comunicación con el servicio seguro de autenticación.'
        };
      }
    },

    isAuthenticated() {
      try {
        const raw = sessionStorage.getItem(STORAGE_KEY);
        if (!raw) return false;
        const session = JSON.parse(raw);
        return !!(session && session.token && session.username);
      } catch (e) {
        return false;
      }
    },

    getCurrentUser() {
      try {
        const raw = sessionStorage.getItem(STORAGE_KEY);
        return raw ? JSON.parse(raw) : null;
      } catch (e) {
        return null;
      }
    },

    async logout() {
      try {
        const raw = sessionStorage.getItem(STORAGE_KEY);
        if (raw) {
          const session = JSON.parse(raw);
          if (session && session.token) {
            fetch('/api/logout', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ token: session.token })
            }).catch(() => {});
          }
        }
      } catch (e) {}

      sessionStorage.removeItem(STORAGE_KEY);
      if (inactivityTimer) {
        clearTimeout(inactivityTimer);
        inactivityTimer = null;
      }
    },

    startInactivityWatcher(onTimeout) {
      if (inactivityTimer) clearTimeout(inactivityTimer);

      const resetTimer = () => {
        if (!this.isAuthenticated()) return;
        clearTimeout(inactivityTimer);
        inactivityTimer = setTimeout(() => {
          this.logout();
          if (typeof onTimeout === 'function') onTimeout();
        }, INACTIVITY_TIMEOUT_MS);
      };

      ['mousedown', 'keydown', 'scroll', 'touchstart'].forEach(evt => {
        window.addEventListener(evt, resetTimer, { passive: true });
      });

      resetTimer();
    }
  };
})();

// ============================================================================
// 3. VALIDACION SEGURA DE ARCHIVOS Y RUTAS (Mitigación CWE-345 / DOM XSS)
// ============================================================================

function esRutaArchivoSegura(ruta) {
  if (typeof ruta !== 'string') return false;
  const rutaLimpia = ruta.trim();

  if (!rutaLimpia.startsWith('actas_organizadas/')) return false;
  if (!rutaLimpia.toLowerCase().endsWith('.pdf')) return false;
  if (rutaLimpia.includes('..') || rutaLimpia.includes('\\')) return false;
  if (rutaLimpia.startsWith('//') || /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(rutaLimpia)) return false;

  const regexSeguro = /^actas_organizadas\/[a-zA-Z0-9_\- ]+\/[a-zA-Z0-9_\- .]+\.pdf$/i;
  return regexSeguro.test(rutaLimpia);
}

function abrirPdfSeguro(ruta) {
  if (!esRutaArchivoSegura(ruta)) {
    mostrarToast('Error de seguridad: La ruta del archivo es inválida o no permitida.');
    return;
  }

  const urlSegura = encodeURI(ruta);
  const ventana = window.open(urlSegura, '_blank', 'noopener,noreferrer');
  if (!ventana) {
    mostrarToast('El navegador bloqueó la ventana emergente. Por favor, autorice popups para este sitio.');
  }
}

function normalizar(txt) {
  return (txt || '').toString().toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}

function nombreDescarga(cedula, nombre) {
  const cedulaLimpia = (cedula || '').toString().replace(/[^a-zA-Z0-9_\-]/g, '');
  const nombreLimpio = (nombre || '').toString()
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9_\- ]/g, '')
    .trim()
    .replace(/\s+/g, '_');
  return `${cedulaLimpia}_${nombreLimpio || 'acta'}.pdf`;
}

let mostrarToast = function (msg) {};

// ============================================================================
// 4. CONTROLADOR DE VISTAS Y LOGICA DE APLICACION
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
  'use strict';

  ThemeManager.init();

  const loginView = document.getElementById('loginView');
  const appView = document.getElementById('appView');
  const loginForm = document.getElementById('loginForm');
  const loginUserInput = document.getElementById('loginUser');
  const loginPassInput = document.getElementById('loginPass');
  const togglePassBtn = document.getElementById('togglePassBtn');
  const loginSubmitBtn = document.getElementById('loginSubmitBtn');
  const loginErrorAlert = document.getElementById('loginErrorAlert');
  const loginErrorMsg = document.getElementById('loginErrorMsg');

  const sessionUserName = document.getElementById('sessionUserName');
  const sessionUserRole = document.getElementById('sessionUserRole');
  const logoutBtn = document.getElementById('logoutBtn');
  
  const searchInput = document.getElementById('searchInput');
  const clearSearchBtn = document.getElementById('clearSearchBtn');
  const sedeFilter = document.getElementById('sedeFilter');
  const pageSizeSelect = document.getElementById('pageSizeSelect');
  const resetBtn = document.getElementById('resetBtn');
  const resultsArea = document.getElementById('resultsArea');
  const countRow = document.getElementById('countRow');
  const pageInfoRow = document.getElementById('pageInfoRow');
  const paginationArea = document.getElementById('paginationArea');
  const toast = document.getElementById('toast');

  let sedesPobladas = false;
  let toastTimer = null;
  let paginaActual = 1;
  let registrosPorPagina = 50;

  mostrarToast = function (msg) {
    if (!toast) return;
    toast.textContent = msg;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toast.classList.remove('show');
    }, 3000);
  };

  function mostrarErrorLogin(msg) {
    if (!loginErrorAlert || !loginErrorMsg) return;
    loginErrorMsg.textContent = msg;
    loginErrorAlert.classList.add('visible');
  }

  function ocultarErrorLogin() {
    if (!loginErrorAlert) return;
    loginErrorAlert.classList.remove('visible');
  }

  if (togglePassBtn && loginPassInput) {
    togglePassBtn.addEventListener('click', () => {
      const esPassword = loginPassInput.type === 'password';
      loginPassInput.type = esPassword ? 'text' : 'password';
      togglePassBtn.setAttribute('aria-label', esPassword ? 'Ocultar contraseña' : 'Ver contraseña');
      
      togglePassBtn.replaceChildren();
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width', '18');
      svg.setAttribute('height', '18');
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor');
      svg.setAttribute('stroke-width', '2');
      svg.setAttribute('stroke-linecap', 'round');
      svg.setAttribute('stroke-linejoin', 'round');

      if (esPassword) {
        const path1 = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path1.setAttribute('d', 'M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24');
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', '1');
        line.setAttribute('y1', '1');
        line.setAttribute('x2', '23');
        line.setAttribute('y2', '23');
        svg.appendChild(path1);
        svg.appendChild(line);
      } else {
        const path1 = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path1.setAttribute('d', 'M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z');
        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.setAttribute('cx', '12');
        circle.setAttribute('cy', '12');
        circle.setAttribute('r', '3');
        svg.appendChild(path1);
        svg.appendChild(circle);
      }
      togglePassBtn.appendChild(svg);
    });
  }

  if (clearSearchBtn && searchInput) {
    searchInput.addEventListener('input', () => {
      if (searchInput.value.trim().length > 0) {
        clearSearchBtn.classList.remove('hidden');
      } else {
        clearSearchBtn.classList.add('hidden');
      }
    });

    clearSearchBtn.addEventListener('click', () => {
      searchInput.value = '';
      clearSearchBtn.classList.add('hidden');
      searchInput.focus();
      paginaActual = 1;
      renderResultados();
    });
  }

  function inicializarSedes() {
    if (sedesPobladas || typeof ACTAS === 'undefined' || !Array.isArray(ACTAS)) return;

    sedeFilter.replaceChildren();
    const optDefault = document.createElement('option');
    optDefault.value = '';
    optDefault.textContent = 'Todas las sedes';
    sedeFilter.appendChild(optDefault);

    const sedesUnicas = [...new Set(ACTAS.map(a => a.sede))].filter(Boolean).sort();
    sedesUnicas.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s;
      opt.textContent = `Sede ${s}`;
      sedeFilter.appendChild(opt);
    });

    sedesPobladas = true;
  }

  function crearEstadoVacio(titulo, descripcion) {
    const card = document.createElement('div');
    card.className = 'empty-state-card';

    const iconDiv = document.createElement('div');
    iconDiv.className = 'empty-state-icon';
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', '24');
    svg.setAttribute('height', '24');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '2');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', '11');
    circle.setAttribute('cy', '11');
    circle.setAttribute('r', '8');
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', '21');
    line.setAttribute('y1', '21');
    line.setAttribute('x2', '16.65');
    line.setAttribute('y2', '16.65');
    svg.appendChild(circle);
    svg.appendChild(line);
    iconDiv.appendChild(svg);
    card.appendChild(iconDiv);

    const h3 = document.createElement('h3');
    h3.className = 'empty-state-title';
    h3.textContent = titulo;
    card.appendChild(h3);

    const p = document.createElement('p');
    p.className = 'empty-state-desc';
    p.textContent = descripcion;
    card.appendChild(p);

    return card;
  }

  function renderPaginacion(totalElementos, paginaAct, porPagina) {
    paginationArea.replaceChildren();
    if (totalElementos <= porPagina) return;

    const totalPaginas = Math.ceil(totalElementos / porPagina);
    const pagesContainer = document.createElement('div');
    pagesContainer.className = 'pagination-pages';

    const btnPrev = document.createElement('button');
    btnPrev.type = 'button';
    btnPrev.className = 'page-btn';
    btnPrev.textContent = '«';
    btnPrev.title = 'Página anterior';
    btnPrev.disabled = paginaAct <= 1;
    btnPrev.addEventListener('click', () => {
      if (paginaAct > 1) {
        paginaActual--;
        renderResultados();
        window.scrollTo({ top: 120, behavior: 'smooth' });
      }
    });
    pagesContainer.appendChild(btnPrev);

    let delta = 2;
    let range = [];
    for (let i = Math.max(2, paginaAct - delta); i <= Math.min(totalPaginas - 1, paginaAct + delta); i++) {
      range.push(i);
    }

    if (paginaAct - delta > 2) {
      range.unshift('...');
    }
    if (paginaAct + delta < totalPaginas - 1) {
      range.push('...');
    }

    range.unshift(1);
    if (totalPaginas > 1) {
      range.push(totalPaginas);
    }

    range.forEach(p => {
      if (p === '...') {
        const span = document.createElement('span');
        span.className = 'page-ellipsis';
        span.textContent = '…';
        pagesContainer.appendChild(span);
      } else {
        const btnPage = document.createElement('button');
        btnPage.type = 'button';
        btnPage.className = `page-btn ${p === paginaAct ? 'active' : ''}`;
        btnPage.textContent = p.toString();
        if (p === paginaAct) {
          btnPage.setAttribute('aria-current', 'page');
        } else {
          btnPage.addEventListener('click', () => {
            paginaActual = p;
            renderResultados();
            window.scrollTo({ top: 120, behavior: 'smooth' });
          });
        }
        pagesContainer.appendChild(btnPage);
      }
    });

    const btnNext = document.createElement('button');
    btnNext.type = 'button';
    btnNext.className = 'page-btn';
    btnNext.textContent = '»';
    btnNext.title = 'Página siguiente';
    btnNext.disabled = paginaAct >= totalPaginas;
    btnNext.addEventListener('click', () => {
      if (paginaAct < totalPaginas) {
        paginaActual++;
        renderResultados();
        window.scrollTo({ top: 120, behavior: 'smooth' });
      }
    });
    pagesContainer.appendChild(btnNext);

    paginationArea.appendChild(pagesContainer);
  }

  function renderResultados() {
    if (!AuthService.isAuthenticated()) {
      resultsArea.replaceChildren();
      countRow.replaceChildren();
      pageInfoRow.replaceChildren();
      paginationArea.replaceChildren();
      return;
    }

    if (typeof ACTAS === 'undefined' || !Array.isArray(ACTAS)) {
      resultsArea.replaceChildren();
      resultsArea.appendChild(
        crearEstadoVacio('Base de datos no encontrada', 'No se pudo cargar la colección de actas digitales (data.js).')
      );
      return;
    }

    const q = normalizar(searchInput.value.trim());
    const sedeSel = sedeFilter.value;

    const filtradas = ACTAS.filter(a => {
      const coincideTexto = !q || normalizar(a.nombre).includes(q) || (a.cedula && a.cedula.toString().includes(q));
      const coincideSede = !sedeSel || a.sede === sedeSel;
      return coincideTexto && coincideSede;
    });

    const totalFiltradas = filtradas.length;
    const totalPaginas = Math.ceil(totalFiltradas / registrosPorPagina) || 1;

    if (paginaActual > totalPaginas) {
      paginaActual = 1;
    }

    countRow.replaceChildren();
    const countStrong = document.createElement('strong');
    countStrong.textContent = totalFiltradas.toLocaleString('es-CO');
    countRow.appendChild(countStrong);
    const countText = document.createTextNode(` acta${totalFiltradas === 1 ? '' : 's'} encontrada${totalFiltradas === 1 ? '' : 's'}`);
    countRow.appendChild(countText);

    pageInfoRow.replaceChildren();
    if (totalFiltradas > 0) {
      const inicio = (paginaActual - 1) * registrosPorPagina + 1;
      const fin = Math.min(paginaActual * registrosPorPagina, totalFiltradas);
      pageInfoRow.textContent = `Página ${paginaActual} de ${totalPaginas} (${inicio} – ${fin})`;
    }

    resultsArea.replaceChildren();

    if (totalFiltradas === 0) {
      paginationArea.replaceChildren();
      resultsArea.appendChild(
        crearEstadoVacio(
          'No se encontraron actas con ese criterio',
          'Revisa que el número de cédula o los nombres estén bien escritos, o limpia los filtros aplicados.'
        )
      );
      return;
    }

    const inicioSlice = (paginaActual - 1) * registrosPorPagina;
    const registrosVisibles = filtradas.slice(inicioSlice, inicioSlice + registrosPorPagina);

    const tableContainer = document.createElement('div');
    tableContainer.className = 'table-container';

    const table = document.createElement('table');
    const thead = document.createElement('thead');
    const trHead = document.createElement('tr');

    ['Cédula / Documento', 'Nombre del Paciente', 'Sede', 'Acciones'].forEach(titulo => {
      const th = document.createElement('th');
      th.textContent = titulo;
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');

    registrosVisibles.forEach(a => {
      const tr = document.createElement('tr');

      // Columna Cédula
      const tdCedula = document.createElement('td');
      tdCedula.className = 'td-cedula';
      tdCedula.textContent = a.cedula || 'N/A';
      tr.appendChild(tdCedula);

      // Columna Nombre (Limpio sin tags "Revisar")
      const tdNombre = document.createElement('td');
      tdNombre.className = 'td-nombre';
      tdNombre.textContent = a.nombre || 'Sin registrar';
      tr.appendChild(tdNombre);

      // Columna Sede
      const tdSede = document.createElement('td');
      tdSede.className = 'td-sede';
      const sedeBadge = document.createElement('span');
      sedeBadge.className = 'sede-badge';
      sedeBadge.textContent = a.sede || 'Sin sede';
      tdSede.appendChild(sedeBadge);
      tr.appendChild(tdSede);

      // Columna Acciones
      const tdAcciones = document.createElement('td');
      const divAcciones = document.createElement('div');
      divAcciones.className = 'acciones';

      // Botón "Ver PDF"
      const btnVer = document.createElement('button');
      btnVer.type = 'button';
      btnVer.className = 'btn-action-view';
      btnVer.title = 'Visualizar acta en nueva pestaña segura';
      
      const svgVer = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svgVer.setAttribute('width', '14');
      svgVer.setAttribute('height', '14');
      svgVer.setAttribute('viewBox', '0 0 24 24');
      svgVer.setAttribute('fill', 'none');
      svgVer.setAttribute('stroke', 'currentColor');
      svgVer.setAttribute('stroke-width', '2');
      svgVer.setAttribute('stroke-linecap', 'round');
      svgVer.setAttribute('stroke-linejoin', 'round');
      const pathEye = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      pathEye.setAttribute('d', 'M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z');
      const circleEye = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circleEye.setAttribute('cx', '12');
      circleEye.setAttribute('cy', '12');
      circleEye.setAttribute('r', '3');
      svgVer.appendChild(pathEye);
      svgVer.appendChild(circleEye);
      btnVer.appendChild(svgVer);

      const spanVer = document.createElement('span');
      spanVer.textContent = 'Ver PDF';
      btnVer.appendChild(spanVer);

      btnVer.addEventListener('click', () => {
        abrirPdfSeguro(a.archivo);
      });
      divAcciones.appendChild(btnVer);

      // Enlace "Descargar"
      const linkDescargar = document.createElement('a');
      linkDescargar.className = 'btn-action-download';
      linkDescargar.setAttribute('rel', 'noopener noreferrer');
      linkDescargar.title = 'Descargar copia del acta en formato PDF';

      const svgDownload = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svgDownload.setAttribute('width', '14');
      svgDownload.setAttribute('height', '14');
      svgDownload.setAttribute('viewBox', '0 0 24 24');
      svgDownload.setAttribute('fill', 'none');
      svgDownload.setAttribute('stroke', 'currentColor');
      svgDownload.setAttribute('stroke-width', '2');
      svgDownload.setAttribute('stroke-linecap', 'round');
      svgDownload.setAttribute('stroke-linejoin', 'round');
      const pathD1 = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      pathD1.setAttribute('d', 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4');
      const polyD2 = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
      polyD2.setAttribute('points', '7 10 12 15 17 10');
      const lineD3 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      lineD3.setAttribute('x1', '12');
      lineD3.setAttribute('y1', '15');
      lineD3.setAttribute('x2', '12');
      lineD3.setAttribute('y2', '3');
      svgDownload.appendChild(pathD1);
      svgDownload.appendChild(polyD2);
      svgDownload.appendChild(lineD3);
      linkDescargar.appendChild(svgDownload);

      const spanDownload = document.createElement('span');
      spanDownload.textContent = 'Descargar';
      linkDescargar.appendChild(spanDownload);

      if (esRutaArchivoSegura(a.archivo)) {
        linkDescargar.href = encodeURI(a.archivo);
        linkDescargar.download = nombreDescarga(a.cedula, a.nombre);
      } else {
        linkDescargar.href = '#';
        linkDescargar.addEventListener('click', (e) => {
          e.preventDefault();
          mostrarToast('Error de validación: Archivo no autorizado para descarga.');
        });
      }
      divAcciones.appendChild(linkDescargar);

      tdAcciones.appendChild(divAcciones);
      tr.appendChild(tdAcciones);

      tbody.appendChild(tr);
    });

    table.appendChild(tbody);
    tableContainer.appendChild(table);
    resultsArea.appendChild(tableContainer);

    renderPaginacion(totalFiltradas, paginaActual, registrosPorPagina);
  }

  function activarVistaAutenticado(user) {
    loginView.classList.add('hidden');
    appView.classList.remove('hidden');

    if (sessionUserName) sessionUserName.textContent = user.name || user.username;
    if (sessionUserRole) sessionUserRole.textContent = user.role || 'Usuario';

    inicializarSedes();
    paginaActual = 1;
    renderResultados();

    AuthService.startInactivityWatcher(() => {
      desactivarVistaAutenticado();
      mostrarToast('Su sesión expiró por inactividad. Por favor inicie sesión nuevamente.');
    });
  }

  function desactivarVistaAutenticado() {
    AuthService.logout();

    appView.classList.add('hidden');
    loginView.classList.remove('hidden');

    searchInput.value = '';
    if (clearSearchBtn) clearSearchBtn.classList.add('hidden');
    sedeFilter.value = '';
    resultsArea.replaceChildren();
    countRow.replaceChildren();
    pageInfoRow.replaceChildren();
    paginationArea.replaceChildren();

    if (loginPassInput) loginPassInput.value = '';
    ocultarErrorLogin();
  }

  // Formulario de Inicio de Sesión
  if (loginForm) {
    loginForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      ocultarErrorLogin();

      const userVal = loginUserInput.value;
      const passVal = loginPassInput.value;

      loginSubmitBtn.disabled = true;
      const btnSpan = loginSubmitBtn.querySelector('span');
      if (btnSpan) btnSpan.textContent = 'Verificando...';

      try {
        const result = await AuthService.authenticate(userVal, passVal);
        if (result.success) {
          activarVistaAutenticado(result.user);
          mostrarToast(`Bienvenido al sistema, ${result.user.name}.`);
        } else {
          mostrarErrorLogin(result.message);
        }
      } catch (err) {
        mostrarErrorLogin('Ocurrió un error en el servicio de autenticación.');
      } finally {
        loginSubmitBtn.disabled = false;
        if (btnSpan) btnSpan.textContent = 'Iniciar Sesión';
      }
    });
  }

  if (logoutBtn) {
    logoutBtn.addEventListener('click', () => {
      desactivarVistaAutenticado();
      mostrarToast('Sesión cerrada de forma segura.');
    });
  }

  searchInput.addEventListener('input', () => {
    paginaActual = 1;
    renderResultados();
  });

  sedeFilter.addEventListener('change', () => {
    paginaActual = 1;
    renderResultados();
  });

  pageSizeSelect.addEventListener('change', () => {
    registrosPorPagina = parseInt(pageSizeSelect.value, 10) || 50;
    paginaActual = 1;
    renderResultados();
  });

  resetBtn.addEventListener('click', () => {
    searchInput.value = '';
    if (clearSearchBtn) clearSearchBtn.classList.add('hidden');
    sedeFilter.value = '';
    pageSizeSelect.value = '50';
    registrosPorPagina = 50;
    paginaActual = 1;
    renderResultados();
    mostrarToast('Filtros restablecidos.');
  });

  if (AuthService.isAuthenticated()) {
    const user = AuthService.getCurrentUser();
    activarVistaAutenticado(user);
  } else {
    desactivarVistaAutenticado();
  }
});
