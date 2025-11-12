import React from 'react';
import { createRoot } from 'react-dom/client';
import MovieSearchComponent from './MovieSearchComponent';
import { preloadCDNData } from './useMovieSearch';

preloadCDNData().then(() => {
  const root = createRoot(document.getElementById('root'));
  root.render(<MovieSearchComponent />);
});
