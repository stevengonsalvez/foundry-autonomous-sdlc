import { render, screen } from './utils'
import HomePage from '../src/pages/home'

test('home page greets with the Track a parcel heading', () => {
  render(<HomePage />)

  // Updated copy: 'Track a parcel'
  expect(screen.getByRole('heading', { name: 'Track a parcel' })).toBeInTheDocument()
})
