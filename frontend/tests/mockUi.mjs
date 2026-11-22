import React from 'react';
export function Empty({ title, description }) {
  return React.createElement('div', { className: 'empty' },
    React.createElement('h3', null, title),
    React.createElement('p', null, description)
  );
}
export function ErrorNotice({ error }) {
  return error ? React.createElement('div', { className: 'notice-error' }, error) : null;
}
export function Loading({ label }) {
  return React.createElement('div', { className: 'loading' }, label);
}
export function Panel({ children, className = '' }) {
  return React.createElement('section', { className: 'panel ' + className }, children);
}
export function PanelTitle({ title, subtitle, action }) {
  return React.createElement('div', { className: 'panel-heading' },
    React.createElement('h2', null, title),
    subtitle && React.createElement('p', null, subtitle),
    action
  );
}
export function Modal({ title, children }) {
  return React.createElement('dialog', { className: 'modal' },
    React.createElement('h2', null, title),
    children
  );
}
export function Submit({ children }) {
  return React.createElement('button', { type: 'submit' }, children);
}
