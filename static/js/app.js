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

  // Data da prova: mostra o campo de mês ou de dia conforme a opção escolhida
  // (e, no onboarding, o nome da prova quando há prova).
  Revisa.metas = function (raiz) {
    if (!raiz) return;
    Array.prototype.forEach.call(raiz.querySelectorAll('[data-meta]'), function (bloco) {
      var nome = bloco.parentNode.querySelector('[data-prova-nome]');
      function atualizar() {
        var r = bloco.querySelector('input[type="radio"]:checked');
        var tipo = r ? r.value : '';
        Array.prototype.forEach.call(bloco.querySelectorAll('[data-meta-se]'), function (l) {
          var ativo = l.getAttribute('data-meta-se') === tipo;
          l.hidden = !ativo;
          l.querySelector('input').required = ativo;
        });
        if (nome) {
          nome.hidden = tipo === 'sem' || !tipo;
          nome.querySelector('input').required = !nome.hidden;
        }
      }
      bloco.addEventListener('change', atualizar);
      atualizar();
    });
  };

  // Estudo de flashcards, como no Anki: espaço (ou Enter) vira o cartão;
  // 1 a 3 respondem; Ctrl+Z desfaz a última resposta. Nada disso vale
  // enquanto você digita (ex.: editando o cartão).
  function digitando(ev) {
    var t = ev.target;
    return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
  }
  Revisa.estudo = function (raiz) {
    var desfazer = document.querySelector('[data-desfazer]');
    var enviado = false;
    document.addEventListener('keydown', function (ev) {
      if (enviado || digitando(ev)) return;
      if ((ev.ctrlKey || ev.metaKey) && (ev.key === 'z' || ev.key === 'Z') && desfazer) {
        ev.preventDefault();
        enviado = true;
        desfazer.submit();
      }
    });
    if (!raiz) return;
    var verso = raiz.querySelector('[data-verso]');
    var botao = raiz.querySelector('[data-virar]');
    var notas = raiz.querySelector('[data-notas]');
    function virar() {
      verso.hidden = false;
      botao.hidden = true;
      notas.hidden = false;
    }
    botao.addEventListener('click', virar);
    notas.addEventListener('submit', function () { enviado = true; });
    document.addEventListener('keydown', function (ev) {
      if (ev.ctrlKey || ev.metaKey || ev.altKey || enviado || digitando(ev)) return;
      if (notas.hidden && (ev.key === ' ' || ev.key === 'Enter')) {
        ev.preventDefault();
        virar();
        return;
      }
      if (!notas.hidden && /^[1-3]$/.test(ev.key)) {
        var b = notas.querySelectorAll('button[name="nota"]')[Number(ev.key) - 1];
        if (b) { enviado = true; b.click(); }
      }
    });
  };

  // Fórmulas dos flashcards (KaTeX): $$ ... $$ (em destaque) ou \( ... \) (no meio do texto).
  Revisa.formulas = function () {
    if (!window.renderMathInElement) return;
    document.querySelectorAll('.fc-texto').forEach(function (el) {
      window.renderMathInElement(el, {
        delimiters: [{ left: '$$', right: '$$', display: true }, { left: '\\(', right: '\\)', display: false }],
        throwOnError: false
      });
    });
  };

  // Colar uma imagem (Ctrl+V) no texto do cartão: ela vai para o campo de imagem daquele lado.
  document.addEventListener('paste', function (ev) {
    var area = ev.target.closest && ev.target.closest('[data-colar]');
    if (!area || !ev.clipboardData) return;
    var arquivo = null;
    Array.prototype.forEach.call(ev.clipboardData.items || [], function (it) {
      if (!arquivo && it.kind === 'file' && /^image\//.test(it.type)) arquivo = it.getAsFile();
    });
    if (!arquivo) return;
    var campo = area.form.querySelector('input[name="' + area.getAttribute('data-colar') + '"]');
    if (!campo || typeof DataTransfer === 'undefined') return;
    ev.preventDefault();
    var dt = new DataTransfer();
    dt.items.add(new File([arquivo], 'imagem-colada.' + (arquivo.type.split('/')[1] || 'png'), { type: arquivo.type }));
    campo.files = dt.files;
    campo.dispatchEvent(new Event('change', { bubbles: true }));
  });
  // Mostra o nome da imagem escolhida/colada ao lado do campo.
  document.addEventListener('change', function (ev) {
    if (!ev.target.matches || !ev.target.matches('[data-imagem]')) return;
    var rotulo = ev.target.closest('label');
    var aviso = rotulo.querySelector('.fc-arquivo-nome') || rotulo.appendChild(document.createElement('small'));
    aviso.className = 'fc-arquivo-nome';
    aviso.textContent = ev.target.files.length ? '✓ ' + ev.target.files[0].name : '';
  });

  // Busca nos cartões de um baralho (filtra a lista enquanto você digita).
  document.addEventListener('input', function (ev) {
    if (!ev.target.matches || !ev.target.matches('[data-busca-cartoes]')) return;
    var q = ev.target.value.trim().toLowerCase();
    document.querySelectorAll('.fc-cartoes > li').forEach(function (li) {
      li.hidden = q && li.getAttribute('data-texto').indexOf(q) === -1;
    });
  });

  // Tela "Ordem": cada lista vira arrastável (SortableJS). Ao soltar, manda a
  // nova ordem dos irmãos para o servidor e mostra "Ordem salva".
  Revisa.ordem = function (token, url) {
    if (!window.Sortable) return;
    var aviso = document.querySelector('[data-ord-aviso]');
    var timer;
    function avisar(texto, erro) {
      aviso.textContent = texto;
      aviso.classList.toggle('erro', !!erro);
      aviso.classList.add('mostra');
      clearTimeout(timer);
      timer = setTimeout(function () { aviso.classList.remove('mostra'); }, 1800);
    }
    document.querySelectorAll('[data-ordem]').forEach(function (lista) {
      window.Sortable.create(lista, {
        handle: '.ord-alca', animation: 150, ghostClass: 'sortable-ghost', chosenClass: 'sortable-chosen',
        onEnd: function (ev) {
          if (ev.oldIndex === ev.newIndex) return;
          var ids = Array.prototype.map.call(lista.children, function (li) { return Number(li.getAttribute('data-id')); });
          fetch(url, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token },
            body: JSON.stringify({ tipo: lista.getAttribute('data-ordem'), ids: ids })
          }).then(function (r) {
            avisar(r.ok ? 'Ordem salva' : 'Não deu para salvar. Recarregue a página.', !r.ok);
          }).catch(function () { avisar('Sem conexão: a ordem não foi salva.', true); });
        }
      });
    });
  };

  // Engrenagem da seção: sem "Questões" marcada, os campos que só valem para
  // questões (dia fixo, limite, ciclo...) somem; ficam ritmo, fase e máximo de dias.
  Revisa.tipoSecao = function (form) {
    if (!form) return;
    var caixa = form.querySelector('input[name="usa_questoes"]');
    var cartoes = form.querySelector('input[name="usa_flashcards"]');
    if (!caixa) return;
    function atualizar() {
      form.querySelectorAll('[data-so-questoes]').forEach(function (b) { b.hidden = !caixa.checked; });
      form.querySelectorAll('[data-so-flashcards]').forEach(function (b) { b.hidden = !(cartoes && cartoes.checked); });
    }
    caixa.addEventListener('change', atualizar);
    if (cartoes) cartoes.addEventListener('change', atualizar);
    atualizar();
  };

  // Configurações: mostra só os blocos que valem para o modo.
  Revisa.config = function (form) {
    if (!form) return;
    function atualizar() {
      var modo = modoAtual(form);
      form.querySelector('[data-secao="dias"]').hidden = !(modo === 'fixa' || modo === 'ambos');
      form.querySelector('[data-secao="minima"]').hidden = !(modo === 'diaria' || modo === 'ambos');
      var dist = form.querySelector('input[name="distribuicao"]:checked');
      var blocoCiclo = form.querySelector('[data-secao="secoes_dia"]');
      if (blocoCiclo) blocoCiclo.hidden = !(dist && dist.value === 'ciclo');
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
    // mesmo arredondamento do servidor: o "meio" vai para baixo (22,5 -> 22)
    return Math.ceil(x - 0.5 - 1e-9);
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

  // Registrar prática: matéria -> assunto.
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

  // Subassuntos recolhíveis: fechados por padrão; o navegador lembra quais
  // ficaram abertos (só neste aparelho). No modo de edição abrem todos.
  var CHAVE_SUBS = 'revisa-subassuntos-abertos';
  var mexendoNosSubs = false;
  function subsAbertos() {
    try { return JSON.parse(localStorage.getItem(CHAVE_SUBS) || '[]'); } catch (e) { return []; }
  }
  function guardarSubs(lista) {
    try { localStorage.setItem(CHAVE_SUBS, JSON.stringify(lista)); } catch (e) {}
  }
  function subsComoGuardados(raiz) {
    var abertos = subsAbertos();
    mexendoNosSubs = true;
    raiz.querySelectorAll('[data-sub]').forEach(function (d) { d.open = abertos.indexOf(d.getAttribute('data-sub')) !== -1; });
    mexendoNosSubs = false;
  }
  function abrirSubs(raiz) {
    mexendoNosSubs = true;
    raiz.querySelectorAll('[data-sub]').forEach(function (d) { d.open = true; });
    mexendoNosSubs = false;
  }
  document.querySelectorAll('[data-sub]').forEach(function (d) {
    if (!d.closest('[data-bloco].editando')) d.open = subsAbertos().indexOf(d.getAttribute('data-sub')) !== -1;
    d.addEventListener('toggle', function () {
      if (mexendoNosSubs || d.closest('[data-bloco].editando')) return;
      var id = d.getAttribute('data-sub');
      var lista = subsAbertos().filter(function (x) { return x !== id; });
      if (d.open) lista.push(id);
      guardarSubs(lista);
    });
  });

  // Matérias: botão Editar/Concluir alterna o modo do bloco sem recarregar.
  document.addEventListener('click', function (ev) {
    var link = ev.target.closest('[data-alternar-edicao]');
    if (!link) return;
    var bloco = link.closest('[data-bloco]');
    if (!bloco) return;
    ev.preventDefault();
    var editar = !bloco.classList.contains('editando');
    document.querySelectorAll('[data-bloco].editando').forEach(function (b) {
      b.classList.remove('editando');
      subsComoGuardados(b);
    });
    if (editar) {
      bloco.classList.add('editando');
      abrirSubs(bloco);   // editando, os subassuntos ficam à mostra
    }
    try { history.replaceState(null, '', link.getAttribute('href')); } catch (e) {}
  });

  // Matéria: os dias só aparecem quando a frequência é "Só em alguns dias".
  function ligarFrequencia(form) {
    var dias = form.querySelector('[data-dias-secao]');
    if (!dias) return;   // sem "cada matéria tem seus dias", o campo nem aparece
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
