## verdict

1. **resolved** — La corrección de estado redundante aparece en las cinco recapturas válidas: [desktop.png](./desktop.png) (revisión en escritorio), [mobile.png](./mobile.png) (revisión móvil), [mobile-held.png](./mobile-held.png) (reservas retenidas durante la pausa), [mobile-unavailable.png](./mobile-unavailable.png) (acceso no disponible) y [mobile-unknown.png](./mobile-unknown.png) (resultado sin confirmar). Los iconos acompañan el estado sin sustituir su texto; PauseCircle acompaña el aviso de pausa con alineación y reflujo correctos. El fragmento correspondiente de [manual-control-panel.tsx](../../../core/components/curve/initiatives/manual-control-panel.tsx) (estado principal y aviso de pausa) confirma `aria-hidden="true"`, `size-4` y `shrink-0` en ambos iconos.

No se observan regresiones introducidas por esta corrección. [measurements.json](./measurements.json) (mediciones de las recapturas sintéticas) mantiene cero errores y anchos de contenido iguales a 1440 y 390 px.

## remaining

clear. Este ship cubre únicamente la corrección puntuada. La evidencia sigue siendo sintética y no acredita integración de navegador/backend, autorización para despliegue ni cualificación del montaje detrás del flag.

disposition: ship
