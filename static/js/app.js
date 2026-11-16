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
      if (n === '2') return modo === 'fixa' || modo === 'ambos';
      if (n === '3') return modo === 'diaria' || modo === 'ambos';
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
      if (passos[atual].getAttribute('data-passo') === '2' && !checarDias(form)) {
        form.querySelector('input[name="dias_fixos"]').reportValidity();
        return;
      }
      atual = proximo(atual, 1);
      mostrar();
    });
    bVoltar.addEventListener('click', function () { atual = Math.max(0, proximo(atual, -1)); mostrar(); });
    form.addEventListener('change', function () { checarDias(form); mostrar(); });
    mostrar();
  };

  // Configurações: mostra só as seções que valem para o modo.
  Revisa.config = function (form) {
    if (!form) return;
    function atualizar() {
      var modo = modoAtual(form);
      form.querySelector('[data-secao="dias"]').hidden = modo === 'diaria';
      form.querySelector('[data-secao="minima"]').hidden = modo === 'fixa';
      checarDias(form);
    }
    form.addEventListener('change', atualizar);
    atualizar();
  };

  // Registrar sessão: matéria -> assunto.
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
      vazio.textContent = isNaN(mid) ? 'Escolha a matéria primeiro' : 'Escolha o assunto…';
      selA.appendChild(vazio);
      lista.forEach(function (a) {
        var o = document.createElement('option');
        o.value = a.id;
        o.textContent = a.nome + (a.n_sessoes ? '' : ' (novo)');
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
    var cor = css.getPropertyValue('--acento').trim() || '#3451d1';
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
          tension: 0.3,
          pointRadius: 4,
          pointHoverRadius: 6,
          pointBackgroundColor: dados.valores.map(function (v) {
            return v >= 85 ? '#1f9d6b' : v >= 50 ? '#e0a020' : '#d9483b';
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

  window.Revisa = Revisa;
})();
