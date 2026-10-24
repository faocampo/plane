disposition: fix

Revisión inicial delegada con el contrato de fallback, sin navegador. La petición, el alcance, la dirección y QUALITY BAR fueron proporcionados explícitamente en el paquete; no faltan requisitos por no estar en archivos separados. El resultado posterior de la corrección se registra en [verdict.md](./verdict.md) (veredicto acotado de iconografía).

## persistence

Pass. [PRODUCT.md](../../../PRODUCT.md) (propósito, límites y principios de Curve) y [DESIGN.md](../../../DESIGN.md) (sistema visual heredado de Curve y Plane) existen. La extensión ordinaria Operate es code-led: comp, seed, placas y fases de reproducción no aplican según el paquete. No se modificó código ni documentación de producto/diseño.

Las cinco capturas requeridas existen, abren correctamente, muestran el inicio del documento y corresponden a sus estados: [desktop.png](./desktop.png) (revisión en escritorio), [mobile.png](./mobile.png) (revisión móvil), [mobile-held.png](./mobile-held.png) (pausa con reservas conservadas), [mobile-unavailable.png](./mobile-unavailable.png) (acceso no disponible) y [mobile-unknown.png](./mobile-unknown.png) (resultado sin confirmar y reintento deliberado). [measurements.json](./measurements.json) (mediciones de la previsualización sintética) registra cero errores y anchos de contenido iguales al viewport a 1440 y 390 px. [gate2-design-detect.json](../../../../../.curve-local/verification/gate2-design-detect.json) (resultado previo del detector) contiene una lista vacía; no se volvió a ejecutar.

## fidelity

| Elemento                | Estado       | Evidencia                                                                                                                                                                                                                                              |
| ----------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| TYPE                    | match        | Tipografía sans compacta, peso claro en títulos y texto operativo; no se introduce una voz display distinta de Inter heredado.                                                                                                                         |
| MATERIAL                | match        | Superficies semánticas y controles Propel, sin física fingida ni nuevos assets.                                                                                                                                                                        |
| GROUND                  | match        | Campo neutro y acento azul operativo coherentes con el mundo heredado. No existe comp con un color absoluto que deba reproducirse.                                                                                                                     |
| Primer viewport y orden | match        | Manual plan, explicación, estado y Refresh preceden a definición, reservas y siguiente decisión. El comienzo de la evidencia queda visible en el viewport móvil.                                                                                       |
| Reflujo móvil           | adaptation   | La lectura vertical y los controles de ancho completo conservan el orden y responden a la necesidad explícita de uso a 390 px; no hay recortes ni desbordamientos visibles.                                                                            |
| Estado redundante       | contradicted | Los estados del panel y el aviso de pausa aparecen solo con texto. [DESIGN.md](../../../DESIGN.md) (sistema visual heredado de Curve y Plane) exige texto e icono en cada estado; el componente no incorpora iconografía para ellos.                   |
| Decisiones y reservas   | match        | Las capturas distinguen revisión, aprobación con reservas, pausa y resultado desconocido. El código exige definición leída, evidencia correspondiente y confirmación humana para habilitar la decisión; release requiere una reconciliación existente. |
| Privacidad y reintento  | match        | Las vistas sin acceso y con resultado desconocido no muestran la definición, evidencia ni reservas previas. El código conserva el comando pendiente para el reintento explícito y bloquea Refresh mientras el resultado es desconocido.                |
| Veracidad del contenido | match        | La cabecera identifica la previsualización como sintética. Esta revisión no acredita integración de navegador/backend ni cualificación del montaje detrás del flag.                                                                                    |

La THESIS operativa, OWN-WORLD heredado, STORY de revisión y reservas, FIRST VIEWPORT centrado en estado/acción y FORM responsive se conservan, salvo la iconografía de estados indicada. Los controles declaran foco visible y estados disabled/loading; las capturas no acreditan una prueba de teclado. No se observaron elementos prohibidos por el craft floor.

## ceiling

El dispositivo nativo que falta es la iconografía discreta de estado, ya establecida en [manual-plan-panel.tsx](../../../core/components/curve/initiatives/manual-plan-panel.tsx) (panel de borrador revisado con iconos Lucide). La densidad, profundidad y tipografía mantienen el carácter operativo; el alcance no justifica ornamentación, assets o motion adicionales.

## material_fixes

1. Fidelidad a OWN-WORLD / regla de estado redundante: incorporar un icono coherente de Lucide junto al estado principal y al aviso de pausa en [manual-control-panel.tsx](../../../core/components/curve/initiatives/manual-control-panel.tsx) (panel de revisión manual y reservas), con `aria-hidden`, tamaño discreto y sin sustituir el texto; recapturar los mismos cinco estados para comprobar alineación y reflujo.

## keep

Conservar el orden estado → definición → reservas → decisión, el acento reservado a la acción, la revisión humana explícita, la reconciliación previa a release y la desaparición del material protegido al perder autoridad o desconocer el resultado.
