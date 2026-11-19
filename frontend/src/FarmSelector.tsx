import { useState, useRef, useEffect, useId, type KeyboardEvent } from 'react';
import { Building2, Check, ChevronDown, RefreshCw } from 'lucide-react';

export interface FarmOption {
  id: string;
  name: string;
}

export interface FarmSelectorProps {
  currentFarmId: string | null;
  farms: FarmOption[];
  isAdmin: boolean;
  isBusy: boolean;
  onSelectFarm: (farmId: string) => void;
}

export function FarmSelector({
  currentFarmId,
  farms,
  isAdmin,
  isBusy,
  onSelectFarm,
}: FarmSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listboxRef = useRef<HTMLUListElement>(null);
  const uniqueId = useId().replace(/:/g, '');

  const options: FarmOption[] = [];
  if (isAdmin) {
    options.push({ id: '', name: 'Panel global' });
  }
  farms.forEach(f => {
    options.push({ id: f.id, name: f.name });
  });

  const selectedFarm = farms.find(f => f.id === currentFarmId);
  const displayName = selectedFarm
    ? selectedFarm.name
    : isAdmin
    ? 'Panel global'
    : farms.length
    ? 'Selecciona un predio'
    : 'Sin predios asignados';

  const subLabel = isAdmin ? 'CONTEXTO DE SOPORTE' : 'PREDIO ACTUAL';
  const isDisabled = isBusy || (!farms.length && !isAdmin);

  useEffect(() => {
    if (!isOpen) return;
    function handleClickOutside(event: MouseEvent | TouchEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('touchstart', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('touchstart', handleClickOutside);
    };
  }, [isOpen]);

  useEffect(() => {
    if (isOpen) listboxRef.current?.focus();
  }, [isOpen]);

  useEffect(() => {
    if (isOpen && highlightedIndex >= 0 && listboxRef.current) {
      const itemEl = listboxRef.current.children[highlightedIndex] as HTMLElement | undefined;
      itemEl?.scrollIntoView({ block: 'nearest' });
    }
  }, [isOpen, highlightedIndex]);

  function handleOpen() {
    if (isDisabled) return;
    setIsOpen(true);
    const selIdx = options.findIndex(o => o.id === (currentFarmId ?? ''));
    setHighlightedIndex(selIdx >= 0 ? selIdx : 0);
  }

  function handleSelect(farmId: string) {
    setIsOpen(false);
    buttonRef.current?.focus();
    if (farmId !== (currentFarmId ?? '')) {
      onSelectFarm(farmId);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement | HTMLUListElement>) {
    if (isDisabled) return;

    if (!isOpen) {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(event.key)) {
        event.preventDefault();
        handleOpen();
      }
      return;
    }

    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        setHighlightedIndex(prev => (prev + 1 < options.length ? prev + 1 : 0));
        break;
      case 'ArrowUp':
        event.preventDefault();
        setHighlightedIndex(prev => (prev - 1 >= 0 ? prev - 1 : options.length - 1));
        break;
      case 'Home':
        event.preventDefault();
        setHighlightedIndex(0);
        break;
      case 'End':
        event.preventDefault();
        setHighlightedIndex(options.length - 1);
        break;
      case 'Enter':
      case ' ':
        event.preventDefault();
        if (highlightedIndex >= 0 && highlightedIndex < options.length) {
          handleSelect(options[highlightedIndex].id);
        }
        break;
      case 'Escape':
        event.preventDefault();
        setIsOpen(false);
        buttonRef.current?.focus();
        break;
      case 'Tab':
        buttonRef.current?.focus();
        setIsOpen(false);
        break;
    }
  }

  const buttonId = `farm-select-btn-${uniqueId}`;
  const listboxId = `farm-select-list-${uniqueId}`;

  return (
    <div className="farm-switch v3-farm-switch custom-farm-switch" ref={containerRef}>
      <button
        type="button"
        id={buttonId}
        ref={buttonRef}
        className={`farm-selector-trigger ${isOpen ? 'open' : ''} ${isBusy ? 'busy' : ''}`}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={isOpen ? listboxId : undefined}
        aria-label={`${subLabel}: ${displayName}`}
        disabled={isDisabled}
        onClick={() => (isOpen ? setIsOpen(false) : handleOpen())}
        onKeyDown={handleKeyDown}
        title={displayName}
      >
        <div className="farm-icon" aria-hidden="true">
          <Building2 size={16} />
        </div>
        <div className="farm-selector-content">
          <small>{subLabel}</small>
          <strong>{displayName}</strong>
        </div>
        {isBusy ? (
          <RefreshCw size={14} className="spin farm-selector-spinner" aria-label="Cambiando predio…" />
        ) : (
          <ChevronDown size={15} className={`farm-selector-chevron ${isOpen ? 'rotated' : ''}`} aria-hidden="true" />
        )}
      </button>

      {isOpen && (
        <div className="farm-selector-dropdown">
          <ul
            id={listboxId}
            role="listbox"
            aria-label="Predios autorizados"
            aria-activedescendant={highlightedIndex >= 0 ? `farm-opt-${uniqueId}-${highlightedIndex}` : undefined}
            onKeyDown={handleKeyDown}
            tabIndex={-1}
            ref={listboxRef}
            className="farm-selector-list"
          >
            {options.map((option, index) => {
              const isSelected = option.id === (currentFarmId ?? '');
              const isHighlighted = index === highlightedIndex;
              return (
                <li
                  key={option.id || '__global'}
                  id={`farm-opt-${uniqueId}-${index}`}
                  role="option"
                  aria-selected={isSelected}
                  className={`farm-selector-option ${isSelected ? 'selected' : ''} ${
                    isHighlighted ? 'highlighted' : ''
                  }`}
                  onClick={() => handleSelect(option.id)}
                  onMouseEnter={() => setHighlightedIndex(index)}
                  title={option.name}
                >
                  <span className="farm-option-name">{option.name}</span>
                  {isSelected && <Check size={14} className="farm-option-check" aria-hidden="true" />}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
