require_relative 'service'

def run
  s = Service.new
  s.handle('x')
end
