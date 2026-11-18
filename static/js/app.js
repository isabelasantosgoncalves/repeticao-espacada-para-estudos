/* Revisa: interações leves. A validação definitiva sempre acontece no servidor. */
(function () {
  'use strict';

  // Formulários com data-confirmar pedem confirmação antes de enviar (exclusões).
  document.addEventListener('submit', function (ev) {
    var msg = ev.target.getAttribute('data-confirmar');
    if (msg && !window.confirm(msg)) ev.preventDefault();
  });

  // Acertos <= total, com aviso no próprio campo.
  function ligarValidacao(form) {
    var pares = [];
    form.querySelectorAll('[data-acertos]').forEach(function (ac) {
      var linha = ac.closest('.tr-linha') || form;
      var tot = linha.querySelector('[data-total]');
      if (tot) pares.push([ac, tot]);
    });
    var previa = form.querySelector('[data-previa]');

    function checar() {
      pares.forEach(function (p) {
        var a = parseInt(p[0].value, 10), t = parseInt(p[1].value, 10);
        var msg = '';
        if (p[0].value !== '' && !isNaN(a) && !isNaN(t) && a > t) msg = 'Os acertos não podem passar do total.';
        p[0].setCustomValidity(msg);
        if (previa) {
          previa.textContent = (!isNaN(a) && !isNaN(t) && t > 0 && a <= t)
            ? 'Resultado: ' + Math.round(a / t * 100) + '% de acerto' : '';
        }
      });
    }
    form.addEventListener('input', checar);
    checar();
  }
  document.querySelectorAll('[data-validar-resultados]').forEach(ligarValidacao);

  function modoAtual(form) {
    var r = form.querySelector('input[name="modo"]:checked');
    return r ? r.value : null;
  }

  // Exige ao menos um dia fixo quando o modo usa revisão fixa.
  function checarDias(form) {
    var modo = modoAtual(form);
    var marcados = form.querySelectorAll('input[name="dias_fixos"]:checked').length;
    var primeiro = form.querySelector('input[name="dias_fixos"]');
    if (!primeiro) return true;
    var precisa = modo === 'fixa' || modo === 'ambos';
    primeiro.setCustomValidity(precisa && !marcados ? 'Escolha pelo menos um dia.' : '');
    return !(precisa && !marcados);
  }

  var Revisa = {};

  // Onboarding em passos. Pula os passos que não se aplicam ao modo escolhido.
  Revisa.onboarding = function (form) {
    if (!form) return;
    var passos = Array.prototype.slice.call(form.querySelectorAll('.passo'));
    var marcas = document.querySelectorAll('.progresso li');
    var bVoltar = form.querySelector('[data-acao="voltar"]');
    var bAvancar = form.querySelector('[data-acao="avancar"]');
    var bConcluir = form.querySelector('[data-acao="concluir"]');
    var atual = 0;

    function aplicavel(i) {
      var modo = modoAtual(form);
      var n = passos[i].getAttribute('data-passo');
      if (n === 'dias') return modo === 'fixa' || modo === 'ambos';
      if (n === 'minima') return modo === 'diaria' || modo === 'ambos';
      return true;
    }
    function proximo(i, dir) {
      var j = i + dir;
      while (j >= 0 && j < passos.length && !aplicavel(j)) j += dir;
      return j;
    }
    function mostrar() {
      passos.forEach(function (p, i) { p.hidden = i !== atual; });
      marcas.forEach(function (m, i) { m.classList.toggle('on', i <= atual); });
      bVoltar.hidden = atual === 0;
      var ultimo = proximo(atual, 1) >= passos.length;
      bAvancar.hidden = ultimo;
      bConcluir.hidden = !ultimo;
    }
    bAvancar.addEventListener('click', function () {
      if (passos[atual].getAttribute('data-passo') === 'dias' && !checarDias(form)) {
        form.querySelector('input[name="dias_fixos"]').reportValidity();
        return;
      }
      atual = proximo(atual, 1);
      mostrar();
    });
    bVoltar.addEventListener('click', function () { atual = Math.max(0, proximo(atual, -1)); mostrar(); });
    // Sugestão: ritmo intenso combina com "todo dia, tudo que vencer".
    // Só muda o modo enquanto a pessoa ainda não escolheu um por conta própria.
    var modoTocado = false;
    var modoPadrao = modoAtual(form);
    form.addEventListener('change', function (ev) {
      if (ev.target.name === 'modo') modoTocado = true;
      if (ev.target.name === 'ritmo' && !modoTocado) {
        var alvo = ev.target.value === 'intenso' ? 'completa' : modoPadrao;
        var radio = form.querySelector('input[name="modo"][value="' + alvo + '"]');
        if (radio) radio.checked = true;
      }
      checarDias(form);
      mostrar();
    });
    mostrar();
  };

  // Configurações: mostra só as seções que valem para o modo.
  Revisa.config = function (form) {
    if (!form) return;
    function atualizar() {
      var modo = modoAtual(form);
      form.querySelector('[data-secao="dias"]').hidden = !(modo === 'fixa' || modo === 'ambos');
      form.querySelector('[data-secao="minima"]').hidden = !(modo === 'diaria' || modo === 'ambos');
      checarDias(form);
    }
    form.addEventListener('change', atualizar);
    atualizar();
  };

  // Teto de dias: sugere um valor pelo ritmo e pela fase de aprendizado.
  // `auto` (onboarding): o campo acompanha a sugestão até a pessoa escolher outro valor.
  Revisa.teto = function (form, auto) {
    var box = form && form.querySelector('[data-teto]');
    if (!box) return;
    var sugestoes = JSON.parse(box.getAttribute('data-sugestoes'));
    var campo = box.querySelector('input[name="teto_dias"]');
    var alvo = box.querySelector('[data-sugestao]');
    var escolhido = !auto;

    function valor(nome, padrao) {
      var r = form.querySelector('input[name="' + nome + '"]:checked');
      return r ? r.value : padrao;
    }
    function sugestao() {
      var porRitmo = sugestoes[valor('ritmo', 'leve')] || {};
      return porRitmo[valor('aprendizado', 'padrao')] || 45;
    }
    function marcar() {
      box.querySelectorAll('.chip-teto').forEach(function (b) {
        b.classList.toggle('on', b.getAttribute('data-valor') === String(campo.value));
      });
    }
    function atualizar() {
      var s = sugestao();
      alvo.textContent = s;
      if (!escolhido) campo.value = s;
      marcar();
    }
    box.addEventListener('click', function (ev) {
      var chip = ev.target.closest('.chip-teto');
      if (chip) { campo.value = chip.getAttribute('data-valor'); escolhido = true; marcar(); }
      if (ev.target.closest('[data-usar-sugestao]')) { campo.value = sugestao(); escolhido = !auto; marcar(); }
    });
    campo.addEventListener('input', function () { escolhido = true; marcar(); });
    form.addEventListener('change', function (ev) {
      if (ev.target.name === 'ritmo' || ev.target.name === 'aprendizado') atualizar();
    });
    atualizar();
  };

  // Mapa: os contadores do topo filtram a lista por status.
  Revisa.filtroMapa = function (barra) {
    if (!barra) return;
    var botoes = barra.querySelectorAll('[data-filtro]');
    var vazio = document.querySelector('.mapa-vazio');
    botoes.forEach(function (b) {
      b.addEventListener('click', function () {
        var f = b.getAttribute('data-filtro');
        botoes.forEach(function (x) {
          x.classList.toggle('on', x === b);
          x.setAttribute('aria-selected', x === b ? 'true' : 'false');
        });
        var algum = false;
        document.querySelectorAll('[data-secao-mapa]').forEach(function (sec) {
          var visiveis = 0;
          sec.querySelectorAll('li[data-status]').forEach(function (li) {
            var mostra = f === 'todos' || li.getAttribute('data-status') === f;
            li.hidden = !mostra;
            if (mostra) visiveis++;
          });
          sec.hidden = visiveis === 0;
          if (visiveis) algum = true;
        });
        if (vazio) vazio.hidden = algum;
      });
    });
  };

  // Fase de aprendizado: mostra a sequência de cada opção já com o ritmo e o
  // máximo de dias escolhidos (mesma conta do servidor: arredonda "meio para o par").
  function arredondar(x) {
    var f = Math.floor(x), d = x - f;
    if (Math.abs(d - 0.5) < 1e-9) return f % 2 === 0 ? f : f + 1;
    return Math.round(x);
  }
  Revisa.sequencias = function (form) {
    var box = form && form.querySelector('[data-fases]');
    if (!box) return;
    var fatores = JSON.parse(box.getAttribute('data-fatores'));
    function atualizar() {
      var r = form.querySelector('input[name="ritmo"]:checked');
      var fator = fatores[r ? r.value : 'leve'] || 1;
      var campo = form.querySelector('input[name="teto_dias"]');
      var teto = campo && parseInt(campo.value, 10) > 0 ? parseInt(campo.value, 10) : Infinity;
      box.querySelectorAll('[data-seq]').forEach(function (el) {
        var dias = [];
        el.getAttribute('data-seq').split(',').forEach(function (n) {
          var d = Math.min(Math.max(1, arredondar(parseInt(n, 10) * fator)), teto);
          if (dias[dias.length - 1] !== d) dias.push(d);
        });
        el.textContent = dias.join(' → ');
      });
    }
    form.addEventListener('change', atualizar);
    form.addEventListener('input', atualizar);
    form.addEventListener('click', function (ev) { if (ev.target.closest('.chip-teto, [data-usar-sugestao]')) setTimeout(atualizar, 0); });
    atualizar();
  };

  // Registrar prática: seção -> assunto.
  Revisa.seletorAssunto = function () {
    var selM = document.getElementById('sel-materia');
    var selA = document.getElementById('sel-assunto');
    var dados = document.getElementById('dados-assuntos');
    if (!selM || !selA || !dados) return;
    var assuntos = JSON.parse(dados.textContent);
    var inicial = selA.getAttribute('data-valor');

    function preencher() {
      var mid = parseInt(selM.value, 10);
      selA.innerHTML = '';
      var lista = assuntos.filter(function (a) { return a.materia_id === mid; });
      var vazio = document.createElement('option');
      vazio.value = '';
      vazio.textContent = isNaN(mid) ? 'Escolha a seção primeiro' : 'Escolha o assunto…';
      selA.appendChild(vazio);
      lista.forEach(function (a) {
        var o = document.createElement('option');
        o.value = a.id;
        o.textContent = (a.rotulo || a.nome) + (a.n_sessoes ? '' : ' (novo)');
        if (String(a.id) === inicial) o.selected = true;
        selA.appendChild(o);
      });
      if (lista.length === 1) selA.value = lista[0].id;
    }
    selM.addEventListener('change', function () { inicial = null; preencher(); });
    preencher();
  };

  // Histórico: gráfico de linha da % de acerto.
  Revisa.grafico = function (canvas, dados) {
    if (!canvas || !window.Chart) return;
    var css = getComputedStyle(document.documentElement);
    var cor = css.getPropertyValue('--acento').trim() || '#1f5c45';
    Chart.defaults.font.family = '"IBM Plex Mono", monospace';
    Chart.defaults.font.size = 11;
    var texto = css.getPropertyValue('--texto-2').trim() || '#5b6476';
    var grade = css.getPropertyValue('--linha').trim() || '#e6e4dd';
    new Chart(canvas, {
      type: 'line',
      data: {
        labels: dados.labels,
        datasets: [{
          label: '% de acerto',
          data: dados.valores,
          borderColor: cor,
          backgroundColor: cor + '22',
          fill: true,
          tension: 0,
          borderWidth: 2,
          pointRadius: 4,
          pointHoverRadius: 6,
          pointBackgroundColor: dados.valores.map(function (v) {
            return v >= 85 ? '#3d8a5c' : v >= 50 ? '#c08e2c' : '#b04a3a';
          }),
          pointBorderColor: '#fff',
          pointBorderWidth: 1.5
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: { min: 0, max: 100, ticks: { callback: function (v) { return v + '%'; }, color: texto, stepSize: 25 },
               grid: { color: grade } },
          x: { ticks: { color: texto, maxRotation: 0, autoSkip: true }, grid: { display: false } }
        },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: function (c) { return c.parsed.y + '% de acerto'; } } }
        }
      }
    });
  };

  // Matérias: botão Editar/Concluir alterna o modo do bloco sem recarregar.
  document.addEventListener('click', function (ev) {
    var link = ev.target.closest('[data-alternar-edicao]');
    if (!link) return;
    var bloco = link.closest('[data-bloco]');
    if (!bloco) return;
    ev.preventDefault();
    var editar = !bloco.classList.contains('editando');
    document.querySelectorAll('[data-bloco].editando').forEach(function (b) { b.classList.remove('editando'); });
    if (editar) bloco.classList.add('editando');
    try { history.replaceState(null, '', link.getAttribute('href')); } catch (e) {}
  });

  // Seção: os dias só aparecem quando a frequência é "Só em alguns dias".
  function ligarFrequencia(form) {
    var dias = form.querySelector('[data-dias-secao]');
    function atualizar() {
      var r = form.querySelector('input[name="frequencia"]:checked');
      dias.hidden = !(r && r.value === 'dias');
    }
    form.addEventListener('change', atualizar);
    atualizar();
  }
  document.querySelectorAll('[data-frequencia]').forEach(ligarFrequencia);

  // Formulários de edição: o botão Salvar só aparece quando algo mudou.
  document.addEventListener('input', function (ev) {
    var form = ev.target.closest('[data-sujo], .ed-novo');
    if (!form) return;
    var mudou = Array.prototype.some.call(form.elements, function (el) {
      if (el.type === 'text') return form.classList.contains('ed-novo') ? el.value.trim() !== '' : el.value !== el.defaultValue;
      if (el.tagName === 'SELECT') return !el.options[el.selectedIndex].defaultSelected;
      return false;
    });
    form.classList.toggle('sujo', mudou);
  });
  document.addEventListener('change', function (ev) {
    if (ev.target.tagName === 'SELECT' && ev.target.closest('[data-sujo]')) {
      ev.target.dispatchEvent(new Event('input', { bubbles: true }));
    }
  });

  window.Revisa = Revisa;

  // Service worker: permite instalar o Revisa como app (Chrome/Edge/Android).
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js').catch(function () {});
    });
  }
})();
