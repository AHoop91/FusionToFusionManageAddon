/**
 * The checks Fusion Manage puts on a field (its ``fieldValidators``), made in the form before anything is sent, so a mistake is told at once and
 * beside the field. ``ns.validators.check(field, value, lookup)`` answers the first thing wrong with a value, in words, or '' when it is fine.
 *
 * Only a check whose meaning is plain is made here. The rest (a value that must be unique, a credit card number, a list of values of a set
 * length, the number of decimals) is left to Fusion Manage, which refuses what is wrong and says so on the form. A check that names another
 * field is skipped when that field is not on the form.
 *
 * ``field`` is ``{title, required, validators: [{name, variables}]}``; ``value`` is what the form would send (text, a link object, a list
 * of them, true for a ticked box, or '' for nothing); ``lookup(id)`` gives ``{title, value}`` of another field on the form, or null.
 */
(function (ns) {
  'use strict';

  const t = ns.i18n.t;

  const WHOLE = /^[+-]?\d+$/;
  const NUMBER = /^[+-]?(\d+\.?\d*|\.\d+)$/;
  const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  function blank(value) {
    return value === '' || value === null || value === undefined || value === false || (Array.isArray(value) && !value.length);
  }

  /** A value as the text the person typed (a link object or a list of them is not text: it has no text checks). */
  function text(value) {
    return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
  }

  function pattern(source) {
    try { return new RegExp(source); } catch (e) { return null; }   // a mask that is not a pattern is left to Fusion Manage
  }

  /** The field a check names (``secondProperty``), as ``{title, value}``; null when it is not on the form. */
  function named(id, lookup) { return lookup(String(id).trim()); }

  function whole(value, vars, field) {
    return text(value) && !WHOLE.test(text(value).trim()) ? t('products.v_integer', { field: field.title }) : '';
  }

  // Each check gets the value, the variables of the validator, the field, and the lookup, and answers a message or ''.
  // A check with a value to look at is skipped for a blank one: whether it may be blank is the business of "required" and the checks below
  // that are about blanks.
  const checks = {
    minlength: function (value, vars, field) {
      const n = parseInt(vars.minlength, 10);
      return !blank(value) && n > 0 && text(value).length < n ? t('products.v_minlength', { field: field.title, n: n }) : '';
    },
    maxlength: function (value, vars, field) {
      const n = parseInt(vars.maxlength, 10);
      return !blank(value) && n > 0 && text(value).length > n ? t('products.v_maxlength', { field: field.title, n: n }) : '';
    },
    integer: whole,
    long: whole,
    float: function (value, vars, field) {
      return text(value) && !NUMBER.test(text(value).trim()) ? t('products.v_float', { field: field.title }) : '';
    },
    floatRange: function (value, vars, field) {
      const n = Number(text(value));
      if (!text(value) || isNaN(n)) return '';   // a value that is not a number is for "float" to say
      const min = vars.min === undefined || vars.min === '' ? -Infinity : Number(vars.min);
      const max = vars.max === undefined || vars.max === '' ? Infinity : Number(vars.max);
      return n < min || n > max ? t('products.v_range', { field: field.title, min: vars.min, max: vars.max }) : '';
    },
    email: function (value, vars, field) {
      return text(value) && !EMAIL.test(text(value).trim()) ? t('products.v_email', { field: field.title }) : '';
    },
    mask: function (value, vars, field) {
      const re = pattern(vars.mask);
      return text(value) && re && !re.test(text(value)) ? t('products.v_mask', { field: field.title }) : '';
    },
    csvMask: function (value, vars, field) {   // every value of a comma separated list
      const re = pattern(vars.mask);
      if (!text(value) || !re) return '';
      const bad = text(value).split(',').some(function (part) { return part.trim() && !re.test(part.trim()); });
      return bad ? t('products.v_mask', { field: field.title }) : '';
    },
    dateNotBefore: function (value, vars, field, lookup) {
      if (blank(value)) return '';
      const named = String(vars.otherDateFields || '').split(',').map(function (id) { return id.trim(); }).filter(Boolean);
      for (let i = 0; i < named.length; i++) {
        const other = lookup(named[i]);
        if (other && !blank(other.value) && text(value) < text(other.value)) {   // dates are written year-month-day, so they compare as text
          return t('products.v_not_before', { field: field.title, other: other.title });
        }
      }
      return '';
    },
    bothOrNone: function (value, vars, field, lookup) {
      const other = named(vars.secondProperty, lookup);
      return other && blank(value) !== blank(other.value) ? t('products.v_both_or_none', { field: field.title, other: other.title }) : '';
    },
    ifOneThanOther: function (value, vars, field, lookup) {
      const other = named(vars.secondProperty, lookup);
      return other && !blank(value) && blank(other.value) ? t('products.v_if_one', { field: field.title, other: other.title }) : '';
    },
    conditionallyRequired: function (value, vars, field, lookup) {
      const other = named(vars.secondProperty, lookup);
      return other && blank(value) && text(other.value) === String(vars.constrainingValue)
        ? t('products.v_cond_required', { field: field.title, other: other.title, value: vars.constrainingValue }) : '';
    },
    oneOrTheOtherNotBoth: function (value, vars, field, lookup) {
      const other = named(vars.secondProperty, lookup);
      return other && blank(value) === blank(other.value) ? t('products.v_one_not_both', { field: field.title, other: other.title }) : '';
    },
    identical: function (value, vars, field, lookup) {
      const other = named(vars.secondProperty, lookup);
      return other && !blank(value) && text(value) !== text(other.value) ? t('products.v_identical', { field: field.title, other: other.title }) : '';
    },
  };

  /** The first thing wrong with ``value`` of ``field``, or ''. */
  function check(field, value, lookup) {
    if (field.required && blank(value)) return t('products.required_field', { field: field.title });
    for (const v of field.validators) {
      const run = checks[v.name];
      const message = run ? run(value, v.variables || {}, field, lookup) : '';   // a check that is not known is left to Fusion Manage
      if (message) return message;
    }
    return '';
  }

  ns.validators = { check: check, blank: blank };
})(window.MfgUi);
