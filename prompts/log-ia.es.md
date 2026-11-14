# Prompt para que una IA haga el log de un vídeo raw

Pégalo junto con el/los archivos `.ai-log.mp4` que salen de Video Processor. Si el vídeo viene en
varios trozos (`.part01`, `.part02`…), súbelos todos en el mismo mensaje, en orden.

---

Te paso gameplay raw (sin micro, sin audio) reducido a 360p y 2 fps. Necesito un **log de tramos
aprovechables** para usarlos luego como b-roll.

**Cómo leer el tiempo.** En la esquina superior izquierda hay un reloj (`hh:mm:ss.mmm`). Es el
tiempo del vídeo ORIGINAL, aunque el archivo sea un trozo. Usa siempre ese reloj, nunca el tiempo
del reproductor. Si en algún momento no se lee, dilo en `notas` en vez de inventarlo.

**Qué quiero.** Una fila por tramo aprovechable de entre 3 y 30 segundos. No describas todo el
vídeo: solo lo que serviría como b-roll (acción, paisaje, construcciones, menús útiles). Si un
momento es especialmente bueno, márcalo con ⭐ al principio de `notas`.

**Formato.** Solo un CSV, con esta cabecera exacta y sin texto alrededor:

```
archivo,entrada,salida,que_se_ve,tipo,calidad,uso_sugerido,notas
```

- `archivo`: el id del archivo, o sea lo que va antes del primer punto del nombre
  (`cards_0007.ai-log.part02.mp4` → `cards_0007`).
- `entrada` y `salida`: `hh:mm:ss` del reloj en pantalla.
- `que_se_ve`: una frase concreta de lo que se ve. No inventes nada que no distingas.
- `tipo`: `accion`, `paisaje`, `construccion`, `menu`, `cinematica` u `otro`.
- `calidad`: `A` usable tal cual, `B` con retoque, `C` descartar (no incluyas las C salvo que
  sirvan de aviso).
- `uso_sugerido`: libre y corto (por ejemplo, "b-roll de peligro", "transición").
- `notas`: fallos, cortes bruscos, spoilers, cosas que no deberían enseñarse, y cualquier duda.

Si no estás seguro de algo, escribe "no estoy seguro" en `notas`.
