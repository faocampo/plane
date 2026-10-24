# Manual Gate 2: documentación de la extensión

Rol documenter ejecutado por un agente delegado genérico con el contrato degradado; no se inyectó el agente shipped.

La extensión Operate conserva el sistema Curve existente. Se documentan el control manual y su montaje desactivado por defecto; no se promueven decisiones locales a reglas globales ni se regeneran producto, diseño o sidecar.

## Evidencia examinada

- [manual-control-panel.tsx](../../../core/components/curve/initiatives/manual-control-panel.tsx) (preparación protegida, revisión, reservas, reconciliación y reintento): sección integrada con título de 16 px, texto operativo de 13 px y detalle de 12 px; controles Propel, colores semánticos, separación vertical de 20 px e iconos Lucide de 16 px ocultos a tecnologías de asistencia. El estado y Refresh preceden a definición, reservas, decisión y evidencia.
- [initiative-workspace.tsx](../../../core/components/curve/initiatives/initiative-workspace.tsx) (montaje en el detalle de Initiative con identidad autenticada) y [manual-plan-panel.tsx](../../../core/components/curve/initiatives/manual-plan-panel.tsx) (borrador guardado e historial de revisiones): la entrada requiere `VITE_CURVE_MANUAL_PLAN_V2_ENABLED === "true"`, viewer autenticado y estado `PLANNING`, `PAUSED` o `CANCELLED`. El borrador se monta cuando existe preparación protegida vigente. Las identidades y versiones delimitan sesiones; las referencias de target se estabilizan para evitar recargas causadas solo por renders.
- [PRODUCT.md](../../../PRODUCT.md) (propósito, principios y límites heredados de Curve), [DESIGN.md](../../../DESIGN.md) (sistema visual heredado), [design.json](../../design.json) (sidecar visual existente), [globals.css](../../../styles/globals.css) (importación del sistema compartido), [variables.css](../../../../../packages/tailwind-config/variables.css) (roles semánticos, familias y escala tipográfica) y [helper.tsx](../../../../../packages/propel/src/button/helper.tsx) (variantes, estados y tamaños de botones Propel): fuentes comparadas sin cambios. Inter e IBM Plex Mono pertenecen al sistema compartido; el panel no introduce una familia ni un token nuevos.
- [review.md](./review.md) (revisión completa inicial) y [verdict.md](./verdict.md) (veredicto posterior limitado a iconografía): el único cambio material solicitado fue añadir iconos al estado y al aviso de pausa. El veredicto registra **resolved / ship** para esa corrección; no acredita aceptación integral de la superficie ni despliegue.
- [desktop.png](./desktop.png) (revisión sintética a 1440 px), [mobile.png](./mobile.png) (revisión sintética a 390 px), [mobile-held.png](./mobile-held.png) (pausa y reservas retenidas), [mobile-unavailable.png](./mobile-unavailable.png) (vista sin acceso) y [mobile-unknown.png](./mobile-unknown.png) (resultado incierto y reintento): las cinco imágenes se abrieron y examinaron. Conservan icono y texto, orden de lectura y controles legibles; las dos últimas no muestran cuerpos, evidencia o reservas previas.
- [measurements.json](./measurements.json) (mediciones de las cinco recapturas sintéticas) registra una lista de errores vacía y `scrollWidth` igual a 1440 o 390 px según el viewport. [gate2-design-detect.json](../../../../../.curve-local/verification/gate2-design-detect.json) (salida previa del detector) contiene una lista vacía; este pase no lo ejecutó de nuevo.

## Contrato observado

La lectura de definición y evidencia es explícita. Cambiar identidad o versión remonta la sesión; Refresh y el retorno de foco o visibilidad retiran el material anterior antes de solicitar el contexto vigente. Si una lectura detecta cambio de acceso o material, limpia el contenido. Durante un comando pendiente, Refresh y las lecturas quedan bloqueados; el envío ya retiró los cuerpos protegidos. Un resultado incierto conserva únicamente en memoria el mismo payload, versión esperada e idempotency key para reintento deliberado; desmontar la sesión lo descarta.

La decisión exige definición leída, evidencia correspondiente cuando aplica y confirmación humana. Reconcile y Release exigen selección de reservas; Release además requiere una referencia de reconciliación. Aprobar reserva tareas y mantiene la ejecución manual. Pausar o cancelar no libera las reservas. Estas condiciones de interfaz no sustituyen la autorización y validación del servidor.

## Resumen del sistema

1. Paleta: superficies neutras y roles semánticos de Plane, azul operativo para la acción y ámbar suave para la pausa.
2. Tipografía: Inter heredado; jerarquía local de 16, 13 y 12 px, sin una nueva voz display.
3. Composición: estado y Refresh primero; definición, reservas, decisión y evidencia después, con reflujo vertical móvil.
4. Componentes: botones compactos Propel, campos con esquinas de 6 px, detalle progresivo y foco visible; sin assets ni elevación nueva.
5. Reglas conservadas: Semantic Token, Redundant Status, One Outcome y Evidence Above Chrome; el panel permanece subordinado al encabezado de la Initiative.

## Archivos escritos y preservados

- [documentation.md](./documentation.md) (este informe de evidencia y límites): creado.
- [brief de control manual](../../surfaces/urve-initiatives-manual-control-panel-tsx-662d2250.md) (contrato local de revisión y reservas): creado con la herramienta soportada `surface-brief write` y releído; sus seis bloques de dirección registran la extensión code-led sin seed ni comp.
- [brief del borrador](../../surfaces/s-curve-initiatives-manual-plan-panel-tsx-3b4c57bc.md) (contrato histórico del borrador manual): actualizado mediante la misma herramienta únicamente en las dos frases de estado que aún afirmaban ausencia de montaje o lo prohibían; ahora reflejan la entrada default-off y la preparación protegida. El resto del contrato se conserva.
- [PRODUCT.md](../../../PRODUCT.md) (producto heredado), [DESIGN.md](../../../DESIGN.md) (sistema heredado) y [design.json](../../design.json) (sidecar heredado): preservados byte por byte. No se modificaron código, tests, capturas, Git ni Docker en este pase.

## Límites de cualificación

La evidencia visual procede de un mock sintético, no de una sesión de navegador conectada al backend. Las últimas correcciones funcionales de identidad, estabilidad de props y entrada default-off se inspeccionaron en código; no constituyen una nueva aceptación visual ni funcional integrada.

[gate2-candidate-final.log](../../../../../.curve-local/verification/gate2-candidate-final.log) (ejecución backend local del candidato) registra 23 pruebas aprobadas. Al delegar este pase, las 100 regresiones integradas seguían en ejecución y las 45 pruebas UI locales debían comprobarse con la suite web completa: este informe no afirma sus resultados. No se ejecutaron suites ni pruebas de teclado, temas, autorización real o navegador/backend durante la documentación. La cualificación integrada y cualquier activación siguen fuera del alcance de este veredicto.

## Drift no canonizado ni reparado

[design.json](../../design.json) (sidecar histórico) conserva `components` y `narrative` bajo `extensions`, aunque el contrato actual los sitúa en la raíz; su snippet histórico de tarjeta usa un glifo de marca de verificación. Los [briefs de Foundation](../../surfaces/core-components-curve-curve-foundation-status-tsx.md) (contrato de la sonda Foundation) y [Home](../../surfaces/core-components-home-root-tsx.md) (contrato de inicio) usan targets relativos a la app, mientras los briefs manuales incluyen el prefijo de la app. Se registra este drift preexistente sin migrarlo ni convertir el glifo en regla: la autorización limita este pase a documentación de una extensión ordinaria.
