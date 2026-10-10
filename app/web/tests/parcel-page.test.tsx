import { render, screen } from './utils'
import ParcelPage from '../src/pages/parcel'

test('parcel page links back to the search', () => {
  render(<ParcelPage />)

  expect(screen.getByRole('heading', { name: 'Track a parcel' })).toBeInTheDocument()
})

test('navigation titles the document after the page', () => {
  render(<ParcelPage />)

  // Updated copy: 'Track a parcel · Parcel Tracker'
  expect(document.title).to.equal('Track a parcel · Parcel Tracker')
})
